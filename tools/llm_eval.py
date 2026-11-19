"""Оценка локальной модели на корпусе обращений (tools/llm_eval/appeals.jsonl).

Корпус — 60 вымышленных обращений (МФСО, куратор, письмо) с эталонными
полями: 1–30 базовые, 31–60 трудные (`"set": "hard"`); реальных персональных
данных нет. Для каждого обращения вызывается
тот же `app.llm.parse_appeal`, что и в АИС, ответ проходит тот же белый
список `clean_suggestion`, затем поля сравниваются с эталоном.

Запуск:
  python tools/llm_eval.py URL [--model ИМЯ] [--timeout 120] [--out отчёт.md]
      [--raw ответы.jsonl]
  python tools/llm_eval.py --selftest   # проверка самого скрипта на фейковом сервере

Порог годности (план 2026-11-12): вид справки ≥ 90 %, медиана ответа ≤ 60 с
(было 10 с; владелец 12.11: «скорость нам не так важна… главное качество»).
Код завершения: 0 — порог пройден (или самопроверка прошла), 1 — нет.
"""
import argparse
import json
import os
import statistics
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import llm  # noqa: E402
from seed import CERT_TYPES  # noqa: E402

CORPUS = os.path.join(ROOT, "tools", "llm_eval", "appeals.jsonl")
TYPES = [(t[0], t[1], t[6]) for t in CERT_TYPES if t[5]]    # активные виды
CODE_ID = {t[0]: i for i, t in enumerate(TYPES, 1)}
ID_CODE = {i: code for code, i in CODE_ID.items()}
FIELDS = ["cert_code", "copies", "delivery", "full_name", "record_book_no",
          "purpose", "post_address"]
CERT_MIN, MEDIAN_MAX_S = 0.90, 60.0


def load_corpus(path=CORPUS):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _norm(s):
    return " ".join(s.lower().replace("ё", "е").split()) if s else s


def _any(expected):
    return expected if isinstance(expected, list) else [expected]


def score(expect, got):
    """Сравнить очищенный ответ с эталоном: {поле: True/False/None(не оценивается)}.

    ФИО и ключ цели в эталоне могут быть списком допустимых вариантов.
    """
    purpose = _norm(got.get("purpose") or "")
    res = {
        "cert_code": ID_CODE.get(got.get("cert_type")) == expect["cert_code"],
        "copies": (got.get("copies") in (None, 1) if expect["copies"] is None
                   else got.get("copies") == expect["copies"]),
        "delivery": got.get("delivery") == expect["delivery"],
        "full_name": _norm(got.get("full_name")) in
                     [_norm(v) for v in _any(expect["full_name"])],
        "record_book_no": got.get("record_book_no") == expect["record_book_no"],
        "purpose": (None if expect["purpose_kw"] is None else
                    any(_norm(k) in purpose for k in _any(expect["purpose_kw"]))),
        "post_address": (got.get("post_address") is None
                         if expect["address_kw"] is None else
                         expect["address_kw"].lower() in
                         (got.get("post_address") or "").lower()),
    }
    return res


def score_rows(corpus, raws):
    """Очистить сырые ответы модели тем же белым списком и сравнить с эталоном."""
    by_id = {r["id"]: r for r in raws}
    rows, times = [], []
    for item in corpus:
        r = by_id[item["id"]]
        raw = r["raw"] if isinstance(r["raw"], dict) else {}
        got = llm.clean_suggestion(raw, CODE_ID, text=item["text"])
        dropped = sorted(k for k, v in raw.items()
                         if v is not None and k not in got
                         and not (k == "cert_code" and "cert_type" in got))
        rows.append({"id": item["id"], "channel": item["channel"],
                     "set": item.get("set", "base"),
                     "expect": item["expect"], "got": got, "error": r["error"],
                     "dropped": dropped, "score": score(item["expect"], got)})
        times.append(r["seconds"])
    return rows, times


def evaluate(url, model="local", timeout=120, raw_path=None, corpus=None):
    corpus = corpus or load_corpus()
    raws = []
    for item in corpus:
        started = time.monotonic()
        try:
            raw = llm.parse_appeal(item["text"], TYPES, url, timeout=timeout,
                                   model=model)
            error = None
        except llm.LlmUnavailable as exc:
            raw, error = {}, str(exc)
        raws.append({"id": item["id"], "raw": raw, "error": error,
                     "seconds": round(time.monotonic() - started, 2)})
    if raw_path:
        with open(raw_path, "w", encoding="utf-8") as f:
            for r in raws:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return score_rows(corpus, raws)


def rescore(raw_path, corpus=None):
    """Пересчитать оценку по сохранённым сырым ответам (без повторного запуска модели)."""
    with open(raw_path, encoding="utf-8") as f:
        raws = [json.loads(line) for line in f if line.strip()]
    return score_rows(corpus or load_corpus(), raws)


def summary(rows, times):
    acc = {}
    for field in FIELDS:
        marks = [r["score"][field] for r in rows if r["score"][field] is not None]
        acc[field] = (sum(marks), len(marks))
    full = sum(all(v is not False for v in r["score"].values()) for r in rows)
    # «Цель» — свободный текст, сотрудник правит его при проверке; ключевое
    # слово эталона ловит не все верные формулировки (место vs причина)
    core = sum(all(v is not False for k, v in r["score"].items() if k != "purpose")
               for r in rows)
    errors = sum(r["error"] is not None for r in rows)
    return {"acc": acc, "full": full, "core": core, "n": len(rows), "errors": errors,
            "median": statistics.median(times), "max": max(times),
            "times": list(times)}


def _cell(ok, n):
    return f"{ok}/{n} ({ok / n:.0%})" if n else "—"


def report_md(s, rows, url, model):
    times = s["times"]
    parts = {name: summary([r for r in rows if r["set"] == key],
                           [t for r, t in zip(rows, times) if r["set"] == key])
             for name, key in (("базовые 1–30", "base"), ("трудные 31–60", "hard"))
             if any(r["set"] == key for r in rows)}
    head = "| Поле | Все | " + " | ".join(parts) + " |"
    lines = [f"Модель: `{model}`, сервер: `{url}`, обращений: {s['n']}, "
             f"ошибок связи/формата: {s['errors']}.", "", head,
             "|---" * (2 + len(parts)) + "|"]
    for field, (ok, n) in s["acc"].items():
        cells = [_cell(*p["acc"][field]) for p in parts.values()]
        lines.append(f"| {field} | {_cell(ok, n)} | " + " | ".join(cells) + " |")
    cells = [_cell(p["core"], p["n"]) for p in parts.values()]
    lines += [f"| все поля, кроме цели | {_cell(s['core'], s['n'])} | "
              + " | ".join(cells) + " |"]
    cells = [_cell(p["full"], p["n"]) for p in parts.values()]
    lines += [f"| все поля обращения | {_cell(s['full'], s['n'])} | "
              + " | ".join(cells) + " |", "",
              f"Время ответа: медиана {s['median']:.1f} с, максимум {s['max']:.1f} с.",
              "", "Расхождения (id: поле — эталон → ответ):", ""]
    for r in rows:
        for field, ok in r["score"].items():
            if ok is False:
                exp = r["expect"].get(field, r["expect"].get(
                    {"purpose": "purpose_kw", "post_address": "address_kw"}.get(field)))
                val = (ID_CODE.get(r["got"].get("cert_type"))
                       if field == "cert_code" else r["got"].get(field))
                lines.append(f"- {r['id']} ({r['channel']}): {field} — {exp!r} → {val!r}")
        if r["dropped"]:
            lines.append(f"- {r['id']}: белый список отбросил {', '.join(r['dropped'])}")
        if r["error"]:
            lines.append(f"- {r['id']}: ошибка {r['error']}")
    return "\n".join(lines) + "\n"


def passed(s):
    ok, n = s["acc"]["cert_code"]
    return ok / n >= CERT_MIN and s["median"] <= MEDIAN_MAX_S


# --- самопроверка на фейковом сервере ---------------------------------------

def _fake_server(answer_for):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            text = body["messages"][-1]["content"].split("<<<\n", 1)[1]
            text = text.rsplit("\n>>>", 1)[0]
            out = json.dumps({"choices": [{"message": {
                "content": json.dumps(answer_for(text), ensure_ascii=False)}}]})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(out.encode())

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def selftest():
    corpus = load_corpus()
    by_text = {c["text"]: c["expect"] for c in corpus}

    def perfect(text):
        e = by_text[text]
        return {"cert_code": e["cert_code"], "copies": e["copies"],
                "delivery": e["delivery"],
                "full_name": _any(e["full_name"])[0],
                "record_book_no": e["record_book_no"],
                "purpose": _any(e["purpose_kw"])[0] or "по месту требования",
                "post_address": (f"г. {e['address_kw']}, ул. Тестовая, 1"
                                 if e["address_kw"] else None)}

    ok = True
    for name, answer, want_cert in (("эталон", perfect, 1.0),
                                    ("пустой ответ", lambda t: {}, 0.0)):
        srv, url = _fake_server(answer)
        try:
            rows, times = evaluate(url, model="fake", timeout=5, corpus=corpus)
            s = summary(rows, times)
            report = report_md(s, rows, url, "fake")  # отчёт тоже должен собираться
            raw_file = os.path.join(os.environ.get("TMPDIR", "/tmp"),
                                    f"llm_eval_selftest_{os.getpid()}.jsonl")
            rows2, _ = evaluate(url, model="fake", timeout=5, corpus=corpus,
                                raw_path=raw_file)
            same = summary(*rescore(raw_file, corpus))["core"] == s["core"]
            os.remove(raw_file)
        finally:
            srv.shutdown()
            srv.server_close()
        cert_ok, n = s["acc"]["cert_code"]
        good = (cert_ok / n == want_cert and (want_cert < 1 or s["full"] == n)
                and "трудные 31–60" in report and same)
        ok &= good
        print(f"{'OK  ' if good else 'FAIL'} {name}: вид справки {cert_ok}/{n}, "
              f"все поля {s['full']}/{n}")
    print(f"корпус: {len(corpus)} обращений")
    print("SELFTEST OK" if ok else "SELFTEST FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url", nargs="?")
    ap.add_argument("--model", default="local")
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--out")
    ap.add_argument("--raw")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--rescore", metavar="RAW.jsonl",
                    help="пересчитать по сохранённым ответам, без модели")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.rescore:
        rows, times = rescore(a.rescore)
        a.url = f"пересчёт {os.path.basename(a.rescore)}"
    elif not a.url:
        ap.error("нужен URL сервера модели, --rescore или --selftest")
    else:
        rows, times = evaluate(a.url, a.model, a.timeout, a.raw)
    s = summary(rows, times)
    text = report_md(s, rows, a.url, a.model)
    print(text)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    print("EVAL PASS" if passed(s) else "EVAL BELOW THRESHOLD")
    return 0 if passed(s) else 1


if __name__ == "__main__":
    sys.exit(main())
