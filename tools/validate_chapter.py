"""Проверка согласованности главы 2 с программой.

Запуск: python tools/validate_chapter.py
Проверяет: существование всех рисунков из glava2.md; сквозную нумерацию
рисунков и таблиц; совпадение числа таблиц ER-модели, информационной модели
и реальной БД SQLite; число экранных форм в 2.4; объём текста; число
операторов в листинге. Итог — CHECKS OK / CHECKS FAIL и честный код выхода.
"""
import ast
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VKR = os.path.join(os.path.dirname(ROOT), "03_Текст ВКР_до 2026-10-28")
if os.path.isdir(os.path.join(VKR, "_рабочие_файлы", "parts")):
    VKR = os.path.join(VKR, "_рабочие_файлы")  # исходники глав после реорганизации папки
G2 = os.path.join(VKR, "parts", "glava2.md")
LST = os.path.join(VKR, "parts", "prilozhenie_listing.md")
BD = os.path.join(VKR, "parts", "prilozhenie_bd.md")
ok = []


def check(name, cond, info=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


text = open(G2, encoding="utf-8").read()
imgs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
missing = [p for p in imgs if not os.path.exists(os.path.normpath(
    os.path.join(VKR, "parts", p)))]
check("все рисунки glava2.md существуют", not missing, f"{len(imgs)} ссылок, нет: {missing}")
figs = [int(n) for n in re.findall(r"(?m)^Рисунок 2\.(\d+) – ", text)]
tabs = [int(n) for n in re.findall(r"(?m)^Таблица 2\.(\d+) – ", text)]
check("рисунки пронумерованы 2.1…2.N подряд", figs == list(range(1, len(figs) + 1)), f"N={len(figs)}")
check("таблицы пронумерованы 2.1…2.N подряд", tabs == list(range(1, len(tabs) + 1)), f"N={len(tabs)}")
check("число подписей = числу изображений", len(figs) == len(imgs))
refs_f = {int(n) for n in re.findall(r"[Рр]исун[а-я]* 2\.(\d+)", text)}
refs_t = {int(n) for n in re.findall(r"[Тт]аблиц[а-я]* 2\.(\d+)", text)}
check("на каждый рисунок есть ссылка в тексте", set(figs) <= refs_f, f"без ссылки: {sorted(set(figs) - refs_f)}")
check("ссылки только на существующие рисунки/таблицы",
      refs_f <= set(figs) and refs_t <= set(tabs), f"{sorted(refs_f - set(figs))} {sorted(refs_t - set(tabs))}")
check("на каждую таблицу есть ссылка в тексте", set(tabs) <= refs_t, f"без ссылки: {sorted(set(tabs) - refs_t)}")
check("нет сокращений «рис.»/«табл.»", not re.search(r"\b(рис|табл)\.", text))
heads = re.findall(r"(?m)^#{1,3} .+$", text)
need = ["## 2.1 Разработка проекта автоматизации",
        "### 2.1.1 Этапы жизненного цикла проекта автоматизации",
        "### 2.1.2 Ожидаемые риски на этапах жизненного цикла и их описание",
        "### 2.1.3 Организационно-правовые и программно-аппаратные средства обеспечения информационной безопасности и защиты информации",
        "## 2.2 Информационное обеспечение задачи",
        "### 2.2.1 Информационная модель и её описание",
        "### 2.2.2 Характеристика нормативно-справочной, входной и оперативной информации",
        "### 2.2.3 Характеристика результатной информации",
        "## 2.3 Программное обеспечение задачи",
        "### 2.3.1 Общие положения (дерево функций и сценарий диалога)",
        "### 2.3.2 Характеристика базы данных",
        "### 2.3.3 Структурная схема пакета (дерево вызова программных модулей)",
        "### 2.3.4 Описание программных модулей",
        "## 2.4 Контрольный пример реализации проекта и его описание",
        "## Выводы по главе 2"]
check("заголовок главы дословно по ИЗ", heads[0] == "# ГЛАВА 2. ПРОЕКТИРОВАНИЕ И РЕАЛИЗАЦИЯ АВТОМАТИЗИРОВАННОЙ ИНФОРМАЦИОННОЙ СИСТЕМЫ УЧЁТА ЗАЯВОК СТУДЕНТОВ НА ПОЛУЧЕНИЕ СПРАВОК НА ПРИМЕРЕ УНИВЕРСИТЕТА «СИНЕРГИЯ»")
check("заголовки параграфов дословно по ИЗ", heads[1:] == need, f"{len(heads)} заголовков")

db = sqlite3.connect("file:" + os.path.join(ROOT, "instance", "ais.sqlite3") + "?mode=ro",
                     uri=True)  # только чтение: демо-БД не изменяется
real = sorted(r[0] for r in db.execute(
    "select name from sqlite_master where type='table' and name not like 'sqlite_%'"))
er_src = open(os.path.join(VKR, "fig", "src", "ris_2_05_er.tables"), encoding="utf-8").read()
im_src = open(os.path.join(VKR, "fig", "src", "ris_2_02_infomodel.dot"), encoding="utf-8").read()
er = sorted(er_src.split())
im = sorted(set(re.findall(r"(?m)^  t_(\w+) \[label=", im_src)))  # хранилища инфомодели
bd = open(BD, encoding="utf-8").read()
doc_tabs = sorted(re.findall(r"(?m)^Таблица А\.\d+ – Структура таблицы (\w+)", bd))
bd_nums = [int(n) for n in re.findall(r"(?m)^Таблица А\.(\d+) – ", bd)]
check("приложение А: заголовок и нумерация А.1…А.N", bd.startswith("# Приложение А. Структура таблиц базы данных")
      and bd_nums == list(range(1, len(bd_nums) + 1)), f"N={len(bd_nums)}")
check("приложение А: «Источник» под каждой таблицей", bd.count("Источник: разработано автором") == len(bd_nums))
# глава ссылается на таблицы приложения А (А.1–А.N по числу таблиц БД) и на
# приложение В (листинг) — по методичке листинг выносится в приложение
check("глава ссылается на приложение А (таблицы А.1–А.N) и на приложение В",
      re.search(rf"А\.1\s*[–-]\s*А\.{len(bd_nums)}\b", text)
      and re.search(r"приложени[а-я]* В\b", text), f"N={len(bd_nums)}")
check("листинг озаглавлен «Приложение В»", open(LST, encoding="utf-8").read().startswith("# Приложение В. Листинг программного кода"))
check("таблицы ER = таблицы БД", er == real, f"ER {len(er)}, БД {len(real)}")
check("объекты инфомодели = таблицы БД", im == real, f"инфомодель {len(im)}")
check("в приложении А описана структура каждой таблицы БД", doc_tabs == real, f"описано {len(doc_tabs)}")

sec24 = text[text.index("## 2.4"):text.index("## Выводы по главе 2")]
screens = re.findall(r"!\[[^\]]*\]\(\.\./fig/scr_", sec24)
check("экранных форм в 2.4 не менее 10", len(screens) >= 10, f"{len(screens)}")

prose = "\n".join(l for l in text.splitlines() if not l.startswith("|"))
prose = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", prose)
tables = "\n".join(l for l in text.splitlines()
                   if l.startswith("|") and not re.match(r"^\|[-| ]+\|$", l))
print(f"INFO знаков: текст вне таблиц {len(prose)}, в таблицах {len(tables)}, "
      f"всего {len(prose) + len(tables)}")

lst = open(LST, encoding="utf-8").read()
code = re.findall(r"```python\n(.*?)```", lst, re.S)
n_ops = sum(sum(isinstance(x, ast.stmt) for x in ast.walk(ast.parse(c))) for c in code)
# объём приложения В (не утверждение текста — его сверяет следующая проверка); 18.11.2026 граница
# поднята с 430 до 450: защита от одновременной смены статуса добавила в services.py 8 операторов
check("листинг (приложение В) ≈ 380–450 операторов", 380 <= n_ops <= 450, f"{n_ops} операторов, {len(code)} фрагментов")
about = re.search(r"около (\d+) операторов", lst)
check("число операторов во введении листинга = round(факт, −1)",
      about and int(about.group(1)) == int(round(n_ops, -1)),
      f"в тексте {about.group(1) if about else '—'}, факт {n_ops}")
# каждый фрагмент — непрерывный участок одного из модулей программы
app_dir = os.path.join(ROOT, "app")
files = [open(os.path.join(d, f), encoding="utf-8").read()
         for d, _, names in os.walk(app_dir) for f in names if f.endswith(".py")]
match = all(any(c.strip() in f for f in files) for c in code)
# 6 статусов в главе совпадают с классификатором программы
from_db = sorted(r[0] for r in db.execute("select code from statuses"))
in_text = sorted(set(re.findall(r"(?m)^\| (NEW|PREP|READY|ISSUED|REJ|CANC) \|", text)))
check("классификатор статусов в главе = таблица statuses (6 статусов)", in_text == from_db, f"{len(in_text)}/{len(from_db)}")
check("законы и ГОСТы оформлены сносками, без [n]",
      not re.search(r"(№ \d+-ФЗ|№ 1119|№ 21|ГОСТ[^\n]{0,25}\d{4}) \[\d", text) and text.count("^[") >= 8, f"сносок {text.count('^[')}")  # модуль или его начало
check("код листинга совпадает с текущими файлами", match)

print("CHECKS OK" if all(ok) else "CHECKS FAIL")
sys.exit(0 if all(ok) else 1)
