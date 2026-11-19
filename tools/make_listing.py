"""Сборка «Приложение В. Листинг программного кода» из реальных модулей.

Запуск: python tools/make_listing.py [файл_вывода]
Каждый фрагмент — непрерывный участок файла модуля (от строки-начала до
строки-конца), поэтому tools/validate_chapter.py может проверить, что код
листинга совпадает с текущими файлами. Операторы считаются как узлы
ast.stmt (простые и составные операторы, включая def/class/import); в текст
приложения попадает только округлённое число («около N операторов»).
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VKR = os.path.join(os.path.dirname(ROOT), "03_Текст ВКР_до 2026-10-28")
if os.path.isdir(os.path.join(VKR, "_рабочие_файлы", "parts")):
    VKR = os.path.join(VKR, "_рабочие_файлы")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    VKR, "parts", "prilozhenie_listing.md")
# (файл, назначение, начало фрагмента или None — с начала файла,
#  конец фрагмента или None — до конца файла; конец в листинг не входит)
MODULES = [
    ("app/workdays.py", "расчёт плановой даты готовности по рабочим дням",
     None, None),
    ("app/services.py", "обработка заявок: нумерация, регистрация заявки, "
     "граф переходов статусов", None, "\n\ndef save_vyzov"),
    ("app/security.py", "безопасность: вход, временная блокировка, "
     "разграничение доступа по ролям, журнал аудита", None, None),
    ("app/llm.py", "разбор обращения локальной языковой моделью и проверка "
     "её ответа кодом; запрос проверки «тип справки — цель»", None, None),
    ("app/type_check.py", "проверка соответствия типа справки цели новых заявок "
     "по расписанию", None, None),
    ("app/certificate.py", "текст справки об обучении и справки-вызова",
     None, "\n\ndef _register_fonts"),
    ("app/views/staff.py", "регистрация заявки из ЕЛК, МФСО или от куратора "
     "и разбор текста обращения", "def _active_types",
     '\n\n@bp.route("/requests/<int:req_id>/vyzov"'),
]


def count(src):
    return sum(isinstance(n, ast.stmt) for n in ast.walk(ast.parse(src)))


def fragment(path, start, end):
    """Непрерывный участок файла; возвращает (текст, полный ли модуль)."""
    full = open(os.path.join(ROOT, path), encoding="utf-8").read()
    a = full.index(start) if start else 0
    b = full.index(end, a) if end else len(full)
    return full[a:b].strip(), (start is None and end is None)


def names(src):
    """Имена функций и классов верхнего уровня во фрагменте."""
    return [n.name for n in ast.parse(src).body
            if isinstance(n, (ast.FunctionDef, ast.ClassDef))]


def main():
    parts, total = [], 0
    for i, (path, title, start, end) in enumerate(MODULES, 1):
        src, whole = fragment(path, start, end)
        total += count(src)
        what = (" Модуль приведён полностью." if whole else
                " Фрагмент модуля: " + ", ".join(names(src)) + ".")
        parts.append(f"## В.{i} Модуль {path}\n\n"
                     f"{title[0].upper()}{title[1:]}.{what}\n\n```python\n{src}\n```\n")
    about = int(round(total, -1))
    head = ("# Приложение В. Листинг программного кода\n\n"
            "Приведены фрагменты основных модулей автоматизированной "
            "информационной системы учёта заявок студентов на получение справок "
            "(язык Python 3, микрофреймворк Flask) — около "
            f"{about} операторов: расчёт плановой даты готовности, обработка заявок "
            "и переходы статусов, средства безопасности, разбор обращения "
            "локальной языковой моделью с проверкой её ответа, проверка "
            "соответствия типа справки цели заявки, формирование текста справки "
            "и справки-вызова, регистрация заявки из другого канала. Остальные "
            "модули, шаблоны экранных форм, автоматизированные тесты и сценарий "
            "заполнения демонстрационными данными входят в электронный комплект "
            "программы.\n\n")
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(head + "\n".join(parts))
    print(f"{OUT}: модулей {len(MODULES)}, операторов {total} (в тексте — около {about})")


if __name__ == "__main__":
    main()
