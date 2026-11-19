"""HTTP-проверки ключевых страниц работающего сервера (без браузера).

Запуск: python tools/http_check.py [base_url]   (по умолчанию http://127.0.0.1:5000)
Печатает строку на каждую проверку и итог CHECKS OK / CHECKS FAIL; код
завершения 0 только если все проверки прошли.
"""
import http.cookiejar
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000"
results = []


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def client():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar),
                                       NoRedirect())


def req(op, path, data=None):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    try:
        r = op.open(BASE + path, body, timeout=10)
        return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def check(name, cond, info=""):
    results.append(cond)
    print(("OK   " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


def login(user, pwd):
    op = client()
    st, _, page = req(op, "/login")
    token = re.search(rb'name="csrf_token" type="hidden" value="([^"]+)"', page).group(1).decode()
    st, h, _ = req(op, "/login", {"login": user, "password": pwd, "csrf_token": token})
    check(f"вход {user}", st == 302, f"{st} -> {h.get('Location')}")
    return op


def main():
    anon = client()
    st, h, _ = req(anon, "/login")
    check("GET /login", st == 200 and h.get("X-Frame-Options") == "DENY", str(st))
    st, h, _ = req(anon, "/staff/")
    check("аноним -> /login", st == 302 and "/login" in h.get("Location", ""), str(st))
    st, _, body = req(client(), "/login", {"login": "student", "password": "student2026"})
    check("POST без CSRF-токена -> 400", st == 400 and "CSRF".encode() in body, str(st))

    s = login("student", "student2026")
    for path, marker in [("/student/", "Личный кабинет"), ("/student/new", "Заявка на получение"),
                         ("/student/requests", "Мои заявки")]:
        st, _, b = req(s, path)
        check(f"студент GET {path}", st == 200 and marker in b.decode(), str(st))
    for path in ("/staff/", "/admin/types"):
        st, _, _ = req(s, path)
        check(f"студент GET {path} -> 403", st == 403, str(st))

    o = login("operator", "operator2026")
    for path, marker in [("/staff/", "Найдено заявок"), ("/staff/?status=NEW", "Новая"),
                         ("/staff/?overdue=1", "просроченные"), ("/staff/reports", "Статистика"),
                         ("/staff/requests/1", "Обработка заявки"),
                         ("/staff/?channel=ELK", "ЕЛК"),
                         ("/staff/requests/new", "Регистрация заявки из другого канала"),
                         ("/staff/reports", "По каналам поступления")]:
        st, _, b = req(o, path)
        check(f"оператор GET {path}", st == 200 and marker in b.decode(), str(st))
    # блок «Текст обращения» (разбор локальной ИИ) — только при заданном AIS_LLM_URL
    llm_on = bool(os.environ.get("AIS_LLM_URL"))
    st, _, b = req(o, "/staff/requests/new")
    check(f"разбор обращения ИИ {'включён' if llm_on else 'выключен'} (AIS_LLM_URL)",
          st == 200 and ("Текст обращения" in b.decode()) == llm_on, str(st))
    st, h, b = req(o, "/staff/export.csv")
    lines = b.decode("utf-8-sig").strip().split("\r\n")
    check("экспорт CSV реестра", st == 200 and h.get("Content-Type", "").startswith("text/csv")
          and lines[0].startswith("Номер;"), f"{len(lines) - 1} строк")
    st, _, b = req(o, "/staff/reports.csv")
    check("экспорт CSV отчёта", st == 200 and "ИТОГО" in b.decode("utf-8-sig"), str(st))
    st, _, b = req(o, "/staff/?q=2026-00001")
    m = re.search(rb'/staff/requests/(\d+)"', b)
    st, h, b = req(o, f"/staff/requests/{m.group(1).decode()}/pdf")
    check("PDF справки (заявка 2026-00001)", st == 200 and b.startswith(b"%PDF"), str(st))
    st, _, b = req(o, "/staff/?type=VYZ&status=ISSUED")
    m = re.search(rb'/staff/requests/(\d+)"', b)
    st, _, b = req(o, f"/staff/requests/{m.group(1).decode()}/print") if m else (0, None, b"")
    check("печать справки-вызова (форма № 1368)", st == 200 and "СПРАВКА-ВЫЗОВ" in b.decode()
          and "линия отрыва" in b.decode(), str(st))
    st, _, _ = req(o, "/admin/users")
    check("оператор GET /admin/users -> 403", st == 403, str(st))

    a = login("admin", "admin2026")
    for path, marker in [("/admin/types", "Справочник типов"), ("/admin/users", "Пользователи"),
                         ("/admin/audit", "Журнал действий"), ("/staff/", "Реестр")]:
        st, _, b = req(a, path)
        check(f"админ GET {path}", st == 200 and marker in b.decode(), str(st))
    st, _, _ = req(a, "/nonexistent")
    check("404 для несуществующей страницы", st == 404, str(st))

    ok = all(results)
    print(f"Проверок: {len(results)}, пройдено: {sum(results)}")
    print("CHECKS OK" if ok else "CHECKS FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
