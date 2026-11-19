"""Оценка проверки «вид справки ↔ цель» на корпусе (tools/llm_eval/purposes.jsonl).

Корпус — 60 вымышленных пар «цель + выбранный вид»: 1–30 выбор верный
(пометки быть не должно), 31–60 выбор ошибочный (`need` — нужный вид).
Для каждой пары вызывается тот же `app.llm.check_type`, что и в команде
`flask check-types`, и тот же `type_verdict`, что ставит пометку.

Запуск:
  python tools/type_eval.py URL [--model ИМЯ] [--timeout 60] [--out отчёт.md]
      [--raw ответы.jsonl]
  python tools/type_eval.py --rescore ответы.jsonl [--out отчёт.md]
  python tools/type_eval.py --selftest   # проверка самого скрипта на фейке

Пороги (план docs/plans/2026-11-13-proverka-vid-cel.md, заданы до замера):
ложных тревог ≤ 1 из 30, поймано ошибочных ≥ 24 из 30, из пойманных верно
назван вид ≥ 90 %, ошибок связи/формата 0. Для другого корпуса (--corpus,
например проверочный purposes_holdout.jsonl) — пропорционально: ложных
≤ max(1, верных/30), поймано ≥ 80 % ошибочных. Код завершения: 0 — пороги
пройдены (или самопроверка прошла), 1 — нет.
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

CORPUS = os.path.join(ROOT, "tools", "llm_eval", "purposes.jsonl")
TYPES = [(t[0], t[1], t[6]) for t in CERT_TYPES if t[5]]    # активные виды
CODES = {t[0] for t in TYPES}
RIGHT_NEED_MIN = 0.90


def false_max(n_ok):
    return max(1, round(n_ok / 30))


def caught_min(n_bad):
    return -(-n_bad * 4 // 5)          # 80 %, с округлением вверх


def load_corpus(path=CORPUS):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def score_rows(corpus, raws):
    by_id = {r["id"]: r for r in raws}
    rows = []
    for item in corpus:
        r = by_id[item["id"]]
        got = llm.type_verdict(r["raw"], item["chosen"], CODES)
        rows.append({**item, "raw": r["raw"], "got": got, "error": r["error"],
                     "seconds": r["seconds"]})
    return rows


def evaluate(url, model="local", timeout=60, raw_path=None, corpus=None):
    corpus = corpus or load_corpus()
    raws = []
    for item in corpus:
        started = time.monotonic()
        try:
            raw = llm.check_type(item["purpose"], item["comment"], TYPES, url,
                                 timeout=timeout, model=model)
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
    with open(raw_path, encoding="utf-8") as f:
        raws = [json.loads(line) for line in f if line.strip()]
    return score_rows(corpus or load_corpus(), raws)


def summary(rows):
    good = [r for r in rows if r["ok"]]
    bad = [r for r in rows if not r["ok"]]
    times = [r["seconds"] for r in rows]
    caught = [r for r in bad if r["got"] is not None]
    return {"n_ok": len(good), "n_bad": len(bad),
            "false": sum(r["got"] is not None for r in good),
            "caught": len(caught),
            "right_need": sum(r["got"] == r["need"] for r in caught),
            "errors": sum(r["error"] is not None for r in rows),
            "median": statistics.median(times), "max": max(times)}


def passed(s):
    return (s["false"] <= false_max(s["n_ok"]) and s["caught"] >= caught_min(s["n_bad"])
            and s["caught"] > 0 and s["right_need"] / s["caught"] >= RIGHT_NEED_MIN
            and s["errors"] == 0)


def _cell(ok, n):
    return f"{ok}/{n} ({ok / n:.0%})" if n else "—"


def report_md(s, rows, url, model):
    lines = [
        f"Модель: `{model}`, сервер: `{url}`, пар: {len(rows)} "
        f"(id {rows[0]['id']}–{rows[-1]['id']}), "
        f"ошибок связи/формата: {s['errors']}.", "",
        "| Показатель | Значение | Порог |", "|---|---|---|",
        f"| Ложные тревоги (выбор верный, а пометка есть) | "
        f"{_cell(s['false'], s['n_ok'])} | ≤ {false_max(s['n_ok'])} |",
        f"| Поймано ошибочных выборов | {_cell(s['caught'], s['n_bad'])} | "
        f"≥ {caught_min(s['n_bad'])} |",
        f"| Из пойманных верно назван нужный вид | "
        f"{_cell(s['right_need'], s['caught'])} | ≥ {RIGHT_NEED_MIN:.0%} |",
        "", f"Время ответа: медиана {s['median']:.1f} с, максимум {s['max']:.1f} с.",
        "", "Расхождения (id: выбран → нужен по эталону; пометка модели):", ""]
    for r in rows:
        want = r["need"]
        if r["got"] != want or r["error"]:
            kind = ("ложная тревога" if r["ok"] else
                    "пропуск" if r["got"] is None else "не тот вид")
            lines.append(f"- {r['id']} [{kind}] «{r['purpose']}»: {r['chosen']} → "
                         f"{want or 'подходит'}; пометка: {r['got'] or 'нет'}; "
                         f"ответ: {json.dumps(r['raw'], ensure_ascii=False)}"
                         + (f"; ошибка {r['error']}" if r["error"] else ""))
    return "\n".join(lines) + "\n"


# --- самопроверка на фейковом сервере ---------------------------------------

def _fake_server(answer_for):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out = json.dumps({"choices": [{"message": {"content": json.dumps(
                answer_for(body["messages"][-1]["content"]), ensure_ascii=False)}}]})
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
    # модель видит только цель: верный вид для цели — выбранный (если выбор
    # верный) или нужный по эталону
    correct = {llm.type_question(c["purpose"], c["comment"]):
               c["chosen"] if c["ok"] else c["need"] for c in corpus}

    def perfect(question):
        return {"suitable_codes": [correct[question]]}

    ok = True
    for name, answer, want_pass in (
            ("эталон", perfect, True),
            ("всегда «OB и все прочие»",
             lambda q: {"suitable_codes": ["OB", "VK", "SZ"]}, False)):
        srv, url = _fake_server(answer)
        try:
            raw_file = os.path.join(os.environ.get("TMPDIR", "/tmp"),
                                    f"type_eval_selftest_{os.getpid()}.jsonl")
            rows = evaluate(url, model="fake", timeout=5, corpus=corpus,
                            raw_path=raw_file)
            s = summary(rows)
            report_md(s, rows, url, "fake")          # отчёт тоже должен собираться
            same = summary(rescore(raw_file, corpus)) == s
            os.remove(raw_file)
        finally:
            srv.shutdown()
            srv.server_close()
        good = (passed(s) == want_pass and same and s["errors"] == 0
                and (not want_pass or (s["false"], s["caught"], s["right_need"])
                     == (0, 30, 30)))
        ok &= good
        print(f"{'OK  ' if good else 'FAIL'} {name}: ложных {s['false']}, "
              f"поймано {s['caught']}, верный вид {s['right_need']}")
    print(f"корпус: {len(corpus)} пар")
    print("SELFTEST OK" if ok else "SELFTEST FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url", nargs="?")
    ap.add_argument("--model", default="local")
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--out")
    ap.add_argument("--raw")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--rescore", metavar="RAW.jsonl")
    ap.add_argument("--corpus", default=CORPUS, help="корпус пар (по умолчанию основной)")
    a = ap.parse_args()
    corpus = load_corpus(a.corpus)
    if a.selftest:
        return selftest()
    if a.rescore:
        rows = rescore(a.rescore, corpus)
        a.url = f"пересчёт {os.path.basename(a.rescore)}"
    elif not a.url:
        ap.error("нужен URL сервера модели, --rescore или --selftest")
    else:
        rows = evaluate(a.url, a.model, a.timeout, a.raw, corpus)
    s = summary(rows)
    text = report_md(s, rows, a.url, a.model)
    print(text)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    print("EVAL PASS" if passed(s) else "EVAL BELOW THRESHOLD")
    return 0 if passed(s) else 1


if __name__ == "__main__":
    sys.exit(main())
