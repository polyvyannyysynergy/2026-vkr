"""Сквозной контрольный пример + снимки экранных форм (Playwright).

Запуск:  python tools/screenshots.py --db ПУТЬ.sqlite3 [--anchor 2026-11-13]
             [--port 5071] [--llm-port 8091]

Скрипт сам готовит отдельную БД (seed.py с опорной датой --anchor в файл
--db; демо-БД instance/ais.sqlite3 не используется и не изменяется), запускает
АИС на --port и сервер-повтор ответов локальной модели на --llm-port, проводит
сценарий и пишет screenshots/*.png, screenshots/control_example.json (номера,
даты, показатели) и screenshots/llm_replay.jsonl (какие ответы модели
воспроизведены).

Сервер-повтор — OpenAI-совместимый /v1/chat/completions, который НЕ генерирует
ответы: на текст обращения он возвращает записанный ответ модели из протокола
замера 13.11.2026 (tools/llm_eval/results/2026-11-13_v2-q30moe.raw.jsonl), на
цель заявки — ответ из протоколов «вид ↔ цель» (…types-q30moe-run3-*.raw.jsonl),
с записанным временем ответа. На запрос, которого нет в протоколах, он отвечает
503 — АИС в этом случае показывает «Модель недоступна».

Окно браузера 1000 × 800 px, device_scale_factor 2; каждый снимок обрезается
по значимой области формы (объединение указанных элементов), чтобы при печати
шириной до 17 см текст интерфейса читался (не мельче 9 пт). Широкие экраны
(отчёт, журнал, страница ошибки) снимаются в более узком окне 560–780 px.
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "screenshots")
EVAL = os.path.join(ROOT, "tools", "llm_eval")
APPEALS = (os.path.join(EVAL, "appeals.jsonl"),
           os.path.join(EVAL, "results", "2026-11-13_v2-q30moe.raw.jsonl"))
PURPOSES = [(os.path.join(EVAL, c), os.path.join(EVAL, "results", r)) for c, r in (
    ("purposes.jsonl", "2026-11-13_types-q30moe-run3-main.raw.jsonl"),
    ("purposes_holdout.jsonl", "2026-11-13_types-q30moe-run3-h1.raw.jsonl"),
    ("purposes_holdout2.jsonl", "2026-11-13_types-q30moe-run3-h2.raw.jsonl"))]
MODEL = "Qwen3-30B-A3B-Instruct-2507"
# Данные сценария, взятые из корпусов замера (ответ модели на них записан):
APPEAL_ID = 20     # сообщение куратора: справка-вызов, АО «Северсталь»
ELK_PURPOSE = 14   # purposes.jsonl: «в военкомат для постановки на воинский учёт» (VK)
WRONG_TYPE = 217   # purposes_holdout2.jsonl: справка об обучении «на работу для
#                    учебного отпуска на сессию», комментарий «заочная форма»
# Карточка студента из обращения куратора (в демо-данных его нет — её создаёт
# администратор; значения вымышленные, как и все демо-данные)
NEW_STUDENT = {"login": "melnikov", "full_name": "Мельников Арсений Олегович",
               "email": "melnikov@student.ais.local", "password": "student2026",
               "record_book_no": "2025-0012", "birth_date": "2001-04-17",
               "faculty": "Факультет экономики и управления",
               "direction": "38.03.01 Экономика", "group_code": "ЭК-251з",
               "course": "2", "study_form": "ZAO", "funding": "DOG",
               "enroll_order": "1312-с", "enroll_date": "2025-08-29",
               "graduation_date": "2030-06-30"}


def read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# --- сервер-повтор ответов модели ------------------------------------------

class Replay:
    def __init__(self, log_path):
        raw = {r["id"]: r for r in read_jsonl(APPEALS[1])}
        self.appeals = {a["text"]: (a["id"], raw[a["id"]]) for a in read_jsonl(APPEALS[0])}
        self.purposes = {}
        for corpus, results in PURPOSES:
            raw = {r["id"]: r for r in read_jsonl(results)}
            for p in read_jsonl(corpus):
                self.purposes[(p["purpose"], p["comment"])] = (
                    os.path.basename(results), p["id"], raw[p["id"]])
        self.log = open(log_path, "w", encoding="utf-8")

    def answer(self, body):
        user = body["messages"][1]["content"]
        m = re.fullmatch(r"Текст обращения:\n<<<\n(.*)\n>>>", user, re.S)
        if m and m.group(1) in self.appeals:
            i, rec = self.appeals[m.group(1)]
            hit = {"kind": "appeal", "file": os.path.basename(APPEALS[1]), "id": i}
        else:
            m = re.fullmatch(r"Цель:\n<<<\n(.*)\n>>>\nКомментарий студента:\n<<<\n(.*)\n>>>",
                             user, re.S)
            key = (m.group(1), None if m.group(2) == "нет" else m.group(2)) if m else None
            if key not in self.purposes:
                self._write({"kind": "unknown", "user": user[:200]})
                return None
            fname, i, rec = self.purposes[key]
            hit = {"kind": "type_check", "file": fname, "id": i}
        hit.update(raw=rec["raw"], seconds=rec["seconds"],
                   schema=body["response_format"]["json_schema"]["name"])
        self._write(hit)
        time.sleep(rec["seconds"])  # записанное время ответа модели
        return rec["raw"]

    def _write(self, item):
        self.log.write(json.dumps(item, ensure_ascii=False) + "\n")
        self.log.flush()


def start_replay(port, replay):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            raw = replay.answer(body)
            if raw is None:
                self.send_response(503)
                self.end_headers()
                return
            data = json.dumps({"choices": [{"message": {
                "role": "assistant", "content": json.dumps(raw, ensure_ascii=False)}}]},
                ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# --- снимки ------------------------------------------------------------------

def shot(page, name, sel="main", cap=760, right=None, pad=8, rpad=0, cut=None):
    """Снимок области: объединение прямоугольников элементов sel (CSS, через «|»),
    высота не более cap CSS px; right — элемент, по правому краю которого
    обрезается снимок (например, столбец таблицы); cut — элементы (строки
    таблицы, поля формы), по нижней границе которых обрезается высота, чтобы
    кадр не проходил посередине строки."""
    page.wait_for_load_state("networkidle")
    # без фокуса ввода и подсветки строки под курсором
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.mouse.move(0, 0)
    box = page.evaluate("""([sel, right]) => {
        const rs = sel.split('|').flatMap(q => [...document.querySelectorAll(q)])
                      .map(e => e.getBoundingClientRect());
        let x0 = Math.min(...rs.map(r => r.left)), y0 = Math.min(...rs.map(r => r.top));
        let x1 = Math.max(...rs.map(r => r.right)), y1 = Math.max(...rs.map(r => r.bottom));
        if (right) { const r = document.querySelector(right).getBoundingClientRect();
                     x1 = Math.min(x1, r.right); }
        return {x: x0 + scrollX, y: y0 + scrollY, w: x1 - x0, h: y1 - y0}; }""",
                        [sel, right])
    if cut and box["h"] > cap:
        bottoms = page.evaluate("""([cut]) => [...document.querySelectorAll(cut)]
            .map(e => e.getBoundingClientRect().bottom + scrollY)""", [cut])
        fit = [b - box["y"] for b in bottoms if 0 < b - box["y"] <= cap]
        cap = (max(fit) if fit else cap) - pad  # нижнее поле не захватывает следующую строку
    clip = {"x": max(box["x"] - pad, 0), "y": max(box["y"] - pad, 0),
            "width": box["w"] + 2 * pad + rpad, "height": min(box["h"], cap) + 2 * pad}
    page.screenshot(path=os.path.join(OUT, name + ".png"), full_page=True, clip=clip)
    print("  снимок", name, f"{int(clip['width'])}×{int(clip['height'])} CSS px")


def login(page, base, user, pwd):
    page.goto(base + "/login")
    page.fill("#login", user)
    page.fill("#password", pwd)
    with page.expect_navigation():
        page.click("button:has-text('Войти')")


def logout(page):
    with page.expect_navigation():
        page.click("button:has-text('Выход')")


def h1_number(page):
    return page.inner_text("h1").split("№")[1].split()[0]


def apply_status(page, code, comment=None):
    page.select_option("#to_status", code)
    if comment:
        page.fill("#comment", comment)
    with page.expect_navigation():
        page.click("button:has-text('Применить')")
    page.wait_for_selector(".alert-success")


def scenario(page, base, env, db_path, result):
    corpus = {p["id"]: p for c, _ in PURPOSES for p in read_jsonl(c)}
    appeal = next(a for a in read_jsonl(APPEALS[0]) if a["id"] == APPEAL_ID)
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        books = dict(con.execute("select u.login, s.record_book_no from users u "
                                 "join students s on s.user_id = u.id"))

    # 1. Вход
    page.goto(base + "/login")
    page.fill("#login", "student")
    shot(page, "01_login", ".login-wrap .card", cap=320)

    # 2. Администратор заводит карточку студента из обращения куратора
    login(page, base, "admin", "admin2026")
    page.goto(base + "/admin/users/new")
    page.select_option("#role", "STUDENT")
    for key, val in NEW_STUDENT.items():
        if key in ("study_form", "funding"):
            page.select_option("#" + key, val)
        else:
            page.fill("#" + key, val)
    shot(page, "24_admin_user_new", "main .col-lg-7 .card")
    page.click("button:has-text('Создать')")
    page.wait_for_selector(".alert-success")
    logout(page)

    # 3. Студентка: кабинет, заявка, карточка, список заявок
    login(page, base, "student", "student2026")
    page.set_viewport_size({"width": 780, "height": 900})
    shot(page, "02_student_dashboard", "main h1|main > .row")
    page.set_viewport_size({"width": 1000, "height": 800})
    page.click("a.nav-link:has-text('Заказать справку')")
    page.select_option("#cert_type", label="Справка об обучении — 2 раб. дн.")
    page.fill("#purpose", "в визовый центр для оформления визы")
    page.fill("#copies", "2")
    page.select_option("#delivery", "EL")
    page.fill("#comment", "Прошу указать полное наименование направления")
    shot(page, "03_request_form", "main .col-lg-7 .card", cap=330, cut="main .col-lg-7 form > div")
    page.click("button:has-text('Подать заявку')")
    page.wait_for_selector("h1:has-text('Заявка №')")
    result["number"] = h1_number(page)
    result["request_url"] = page.url
    result["flash"] = page.inner_text(".alert")
    shot(page, "04_request_created", "h1|main .col-lg-7 .card", cap=330,
         right="main .col-lg-7 .card", cut="main .col-lg-7 tr")
    page.click("a.nav-link:has-text('Мои заявки')")
    shot(page, "05_my_requests", "main .card", right="thead th:nth-child(5)")
    logout(page)

    # 4. Сотрудник: реестр «Новая», просроченные
    login(page, base, "operator", "operator2026")
    page.select_option("select[name=status]", "NEW")
    page.click("button:has-text('Найти')")
    page.wait_for_load_state("networkidle")
    result["registry_new_found"] = page.inner_text("main div.card .small.text-muted")
    result["registry_new_numbers"] = page.eval_on_selector_all(
        "main div.card tbody td:first-child a", "els => els.map(e => e.innerText)")
    shot(page, "06_registry_filter_new", "main > div.card", right="thead th:nth-child(6)", rpad=-6)
    page.goto(base + "/staff/?overdue=1")
    result["registry_overdue_found"] = page.inner_text("main div.card .small.text-muted")
    shot(page, "07_registry_overdue", "main > div.card", right="thead th:nth-child(6)", rpad=-6)

    # 5. Обработка заявки студентки: в работу, готова, печать
    page.goto(base + "/staff/?q=" + result["number"])
    page.click(f"a:has-text('{result['number']}')")
    rid = page.url.rstrip("/").split("/")[-1]
    result["id"] = rid
    page.select_option("#to_status", "PREP")
    page.fill("#comment", "Принята в работу")
    shot(page, "08_process_take", "main .col-lg-5")
    page.click("button:has-text('Применить')")
    page.wait_for_selector(".alert-success")
    apply_status(page, "READY", "Справка подготовлена и подписана деканом")
    shot(page, "09_process_ready", "main .col-lg-5 .card:first-child")
    page.goto(base + f"/staff/requests/{rid}/print")
    shot(page, "10_certificate_print", ".sheet .org|.sheet .dept|.sheet h1|.sheet .num|"
         ".sheet p|.sheet .sign|.sheet .mt-4", cap=1100)

    # 6. Регистрация заявки, принятой через ЕЛК
    elk = corpus[ELK_PURPOSE]
    page.goto(base + "/staff/requests/new")
    page.select_option("#channel", "ELK")
    page.fill("#ext_number", "482913")
    page.fill("#record_book_no", books["petrov"])
    page.select_option("#cert_type", label="Справка для военного комиссариата")
    page.fill("#purpose", elk["purpose"])
    page.select_option("#delivery", "DEAN")
    shot(page, "17_staff_register", "main .col-lg-7 > .card:last-child", cap=470,
         cut="main .col-lg-7 form > div, main .col-lg-7 form > .row")
    page.click("button:has-text('Зарегистрировать')")
    page.wait_for_selector(".alert-success")
    result["elk_number"] = h1_number(page)
    result["elk_flash"] = page.inner_text(".alert-success")
    page.goto(base + "/staff/?channel=ELK")
    result["registry_elk_found"] = page.inner_text("main div.card .small.text-muted")
    shot(page, "18_registry_channels", "main > div.card", cap=430,
         right="thead th:nth-child(6)", rpad=-6, cut="main > div.card tbody tr")

    # 7. Сообщение куратора: разбор локальной моделью, проверка, регистрация
    page.goto(base + "/staff/requests/new")
    page.fill("#text", appeal["text"])
    page.click("button:has-text('Разобрать обращение')")
    page.wait_for_selector(".alert-info", timeout=60000)
    result["llm_alert"] = page.inner_text(".alert-info")
    result["llm_form"] = {k: page.input_value("#" + k) for k in
                          ("cert_type", "purpose", "copies", "delivery", "record_book_no")}
    page.select_option("#channel", "KUR")  # канал выбирает сотрудник, не модель
    shot(page, "21_llm_parse", "main .col-lg-7 > .card:first-child|main .alert-info|"
         "main .col-lg-7 > .card:last-child", cap=900,
         cut="main .col-lg-7 form > div, main .col-lg-7 form > .row")
    page.click("button:has-text('Зарегистрировать')")
    page.wait_for_selector(".alert-success")
    result["vyz_number"] = h1_number(page)
    vid = page.url.rstrip("/").split("/")[-1]
    apply_status(page, "PREP", "Принята в работу")
    page.select_option("#basis", "PA")
    page.fill("#period_from", "2027-01-12")
    page.fill("#period_to", "2027-01-31")
    result["vyz_name_dat_hint"] = page.input_value("#name_dat")
    shot(page, "19_vyzov_data", "main .col-lg-7 .card:last-child")
    page.click("button:has-text('Сохранить данные вызова')")
    page.wait_for_selector(".alert-success")
    apply_status(page, "READY", "Справка-вызов подготовлена и подписана")
    page.goto(base + f"/staff/requests/{vid}/print")
    shot(page, "20_vyzov_print", ".sheet h1|.sheet .num|.sheet p|.sheet .tear|.sheet .sign|"
         ".sheet .mt-3", cap=1200)

    # 8. Новые заявки из демо-данных — в работу (очередь сотрудника)
    page.goto(base + "/staff/?status=NEW")
    queue = [n for n in page.eval_on_selector_all(
        "main div.card tbody td:first-child a", "els => els.map(e => e.innerText)")
        if n != result["elk_number"]]
    for num in queue:
        page.goto(base + "/staff/?q=" + num)
        page.click(f"a:has-text('{num}')")
        apply_status(page, "PREP", "Принята в работу")
    result["taken_to_work"] = queue
    logout(page)

    # 9. Студентка заочной формы выбрала справку об обучении для учебного отпуска
    wrong = corpus[WRONG_TYPE]
    login(page, base, "orlova", "student2026")
    page.click("a.nav-link:has-text('Заказать справку')")
    page.select_option("#cert_type", label="Справка об обучении — 2 раб. дн.")
    page.fill("#purpose", wrong["purpose"])
    page.select_option("#delivery", "DEAN")
    page.fill("#comment", wrong["comment"])
    page.click("button:has-text('Подать заявку')")
    page.wait_for_selector("h1:has-text('Заявка №')")
    result["wrong_type_number"] = h1_number(page)
    logout(page)

    # 10. Проверка «вид ↔ цель» по расписанию — команда flask check-types
    cmd = [sys.executable, "-m", "flask", "--app", "run", "check-types"]
    run = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    result["check_types"] = {"cmd": "flask --app run check-types",
                             "exit": run.returncode,
                             "out": (run.stdout + run.stderr).strip()}
    if run.returncode != 0:
        raise SystemExit(f"check-types: код {run.returncode}: {run.stdout}{run.stderr}")

    # 11. Сотрудник видит подсказку в реестре и на странице заявки
    login(page, base, "operator", "operator2026")
    page.goto(base + "/staff/?status=NEW")
    result["registry_hint_found"] = page.inner_text("main div.card .small.text-muted")
    shot(page, "22_registry_type_hint", "main > div.card", right="thead th:nth-child(6)", rpad=-6)
    page.click(f"a:has-text('{result['wrong_type_number']}')")
    result["type_hint"] = page.inner_text(".alert-warning")
    page.set_viewport_size({"width": 780, "height": 900})
    shot(page, "23_process_type_hint", "main h1|main .alert-warning|main .col-lg-7 > .card:nth-child(2)")
    page.set_viewport_size({"width": 1000, "height": 800})

    # 12. Отчёт за период
    page.goto(base + f"/staff/reports?from=2026-09-01&to={result['anchor']}")
    result["report_tiles"] = page.eval_on_selector_all(
        "main .row.g-3.mb-3 .card-body", "els => els.map(e => e.innerText.replace(/\\n/g, ' | '))")
    result["report_channels"] = page.eval_on_selector_all(
        "main .col-lg-5 .card:first-child tr", "els => els.map(e => e.innerText.replace(/\\t/g, ' | '))")
    # окно 560 px: плитки показателей встают в столбец (в окне 780 px слова
    # в плитках переносятся по слогам, в 1000 px текст на странице мельче 9 пт)
    page.set_viewport_size({"width": 560, "height": 900})
    shot(page, "11_report", "main h1|main > form.card|main .row.g-3.mb-3", cap=1000)
    # окно 780 px: таблицы по каналам и статусам — во всю ширину кадра
    page.set_viewport_size({"width": 780, "height": 900})
    shot(page, "11b_report_channels", "main .col-lg-5 .card:first-child|main .col-lg-5 .card:nth-child(2)")
    page.set_viewport_size({"width": 1000, "height": 800})
    page.goto(base + "/staff/")
    logout(page)

    # 13. Администратор: справочник, журнал
    login(page, base, "admin", "admin2026")
    page.goto(base + "/admin/types")
    shot(page, "12_admin_types", "main .card", cap=1100, right="thead th:nth-child(7)")
    page.goto(base + "/admin/audit")
    page.set_viewport_size({"width": 780, "height": 900})
    shot(page, "14_admin_audit", "main .card table", cap=560, right="thead th:nth-child(5)",
         rpad=-8, cut="main .card tr")
    page.set_viewport_size({"width": 1000, "height": 800})  # меню с кнопкой «Выход»
    logout(page)

    # 14. Студентка: карточка готовой заявки, PDF, попытка открыть реестр
    login(page, base, "student", "student2026")
    page.goto(result["request_url"])
    shot(page, "15_student_card_ready", "h1|main .col-lg-7 .card", right="main .col-lg-7 .card")
    with page.expect_response(lambda r: r.url.endswith("/pdf")) as resp:
        page.evaluate("u => fetch(u)", base + f"/student/requests/{rid}/pdf")
    result["pdf_status"] = resp.value.status
    result["pdf_type"] = resp.value.headers.get("content-type")
    page.goto(base + "/staff/")
    result["student_staff_status"] = page.title()
    page.set_viewport_size({"width": 640, "height": 800})
    shot(page, "16_access_denied", "main .text-center")
    page.set_viewport_size({"width": 1000, "height": 800})


def db_facts(db_path, result):
    """Итоговые числа контрольного примера — прямо из БД сценария."""
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        q = lambda sql: con.execute(sql).fetchall()  # noqa: E731
        result["db"] = {
            "requests": q("select count(*) from requests")[0][0],
            "by_status": dict(q("select s.code, count(*) from requests r join statuses s "
                                "on s.id = r.status_id group by s.code")),
            "by_channel": dict(q("select channel, count(*) from requests group by channel")),
            "students": q("select count(*) from students")[0][0],
            "users": q("select count(*) from users")[0][0],
            "first_created": q("select min(created_at) from requests")[0][0],
            "scenario": q("select r.number, c.code, r.channel, r.ext_number, s.code, "
                          "r.created_at, r.planned_date, r.ready_at from requests r "
                          "join cert_types c on c.id = r.cert_type_id join statuses s "
                          "on s.id = r.status_id where r.created_at >= '"
                          + result["anchor"] + "' order by r.id"),
            "type_checks": q("select r.number, t.code, t2.code, k.model from type_checks k "
                             "join requests r on r.id = k.request_id join cert_types t "
                             "on t.id = r.cert_type_id left join cert_types t2 "
                             "on t2.id = k.suggested_type_id"),
            "audit_llm": q("select action, details from audit_log where action like 'LLM%' "
                           "order by id"),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="файл БД сценария (не instance/ais.sqlite3)")
    ap.add_argument("--anchor", default=time.strftime("%Y-%m-%d"),
                    help="опорная дата демо-данных (по умолчанию — сегодня)")
    ap.add_argument("--port", type=int, default=5071)
    ap.add_argument("--llm-port", type=int, default=8091)
    args = ap.parse_args()
    db_path = os.path.abspath(args.db)
    demo = os.path.realpath(os.path.join(ROOT, "instance", "ais.sqlite3"))
    if os.path.realpath(db_path) == demo:
        sys.exit("--db не должен указывать на демо-БД instance/ais.sqlite3")
    base = f"http://127.0.0.1:{args.port}"
    env = dict(os.environ, AIS_DATABASE=db_path, AIS_LLM_URL=f"http://127.0.0.1:{args.llm_port}",
               AIS_LLM_MODEL=MODEL, AIS_LLM_TIMEOUT="60", LANG="ru_RU.UTF-8")
    env.pop("AIS_DATABASE_URL", None)

    if os.path.exists(db_path):
        os.remove(db_path)
    seed = subprocess.run([sys.executable, "seed.py", args.anchor], cwd=ROOT, env=env,
                          capture_output=True, text=True)
    print(seed.stdout.strip())
    if seed.returncode != 0:
        sys.exit("seed.py: " + seed.stderr)

    for name in os.listdir(OUT):  # снимки прошлых прогонов не смешиваются с новыми
        if name.endswith(".png"):
            os.remove(os.path.join(OUT, name))
    replay = Replay(os.path.join(OUT, "llm_replay.jsonl"))
    llm_srv = start_replay(args.llm_port, replay)
    app_log = open(os.path.join(os.path.dirname(db_path), "screenshots_app.log"), "w")
    app = subprocess.Popen([sys.executable, "-m", "flask", "--app", "run", "run",
                            "--port", str(args.port), "--no-reload"], cwd=ROOT, env=env,
                           stdout=app_log, stderr=subprocess.STDOUT)
    result = {"anchor": args.anchor, "model": MODEL, "db": None}
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/login", timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        with sync_playwright() as p:
            # русская локаль для полей даты (ДД.ММ.ГГГГ)
            browser = p.chromium.launch(args=["--lang=ru-RU"], env=dict(
                os.environ, LANG="ru_RU.UTF-8", LANGUAGE="ru", LC_ALL="ru_RU.UTF-8"))
            ctx = browser.new_context(viewport={"width": 1000, "height": 800},
                                      device_scale_factor=2, locale="ru-RU")
            page = ctx.new_page()
            page.set_default_timeout(30000)
            scenario(page, base, env, db_path, result)
            browser.close()
    finally:
        app.terminate()
        app.wait(timeout=10)
        llm_srv.shutdown()
    db_facts(db_path, result)
    with open(os.path.join(OUT, "control_example.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2, default=str)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    shots = sorted(n for n in os.listdir(OUT) if n.endswith(".png"))
    print(f"снимков: {len(shots)}")


if __name__ == "__main__":
    main()
