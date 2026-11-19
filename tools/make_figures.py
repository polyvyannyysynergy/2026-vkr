"""Генерация рисунков главы 2 ВКР из реальной схемы БД и кода.

Запуск: python tools/make_figures.py [каталог_вывода]
По умолчанию рисунки пишутся в ../03_Текст ВКР_до 2026-10-28/_рабочие_файлы/fig.
ER-диаграмма и информационная модель строятся по метаданным SQLAlchemy:
состав таблиц и связи (внешние ключи) сверяются со схемой БД. Дерево вызова
программных модулей сверяется с фактическими вызовами функций и классов
между модулями пакета app (разбор исходного кода). Скриншоты из screenshots/
копируются в тот же каталог.

Шрифт рисунков — Times New Roman. Рисунки рассчитаны на печать шириной не
более 17 см: в PNG записывается фактическое разрешение (dpi), и скрипт
печатает ожидаемый кегль текста на странице; при кегле схем меньше 10 пт
или тексте, выходящем за рамку блока, он завершается с ошибкой.
"""
import ast
import os
import shutil
import subprocess
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.models import db  # noqa: E402

VKR = os.path.join(os.path.dirname(ROOT), "03_Текст ВКР_до 2026-10-28")
if os.path.isdir(os.path.join(VKR, "_рабочие_файлы", "fig")):
    VKR = os.path.join(VKR, "_рабочие_файлы")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(VKR, "fig")
FONT_DIR = "/System/Library/Fonts/Supplemental"
TNR = os.path.join(FONT_DIR, "Times New Roman.ttf")
TNR_BOLD = os.path.join(FONT_DIR, "Times New Roman Bold.ttf")
FONT = "Times New Roman"
# Graphviz (Pango) читает «Times New Roman» как семейство «Times New» с
# начертанием «Roman» и молча подставляет Helvetica; запятая в конце задаёт
# имя семейства целиком (проверяется в gv_font_check()).
GV_FONT = "Times New Roman,"
FS = 12                  # кегль схем Graphviz, пт (в масштабе 1:1)
MPL_FS = 11              # кегль схем matplotlib, пт (рисунок 1:1 = 17 см)
DPI = 200                # разрешение растра схем
TEXT_W, TEXT_H = 482, 624  # поле набора: 170 × 220 мм в пунктах
PAGE_W = TEXT_W / 72     # ширина поля набора, дюймы
SHOT_DPI = 192           # скриншоты сняты с device_scale_factor 2
TITLES = {  # русские названия таблиц для рисунков
    "roles": "Роли", "users": "Пользователи", "students": "Студенты",
    "cert_types": "Типы справок", "statuses": "Статусы заявок",
    "requests": "Заявки", "status_history": "История статусов",
    "type_checks": "Проверки типа справки", "audit_log": "Журнал аудита"}
ORDER = ["roles", "users", "students", "cert_types", "statuses", "requests",
         "status_history", "type_checks", "audit_log"]
report = []
overflow = []


def set_dpi(path, dpi):
    Image.open(path).save(path, dpi=(dpi, dpi))


def note(path, dpi, min_font):
    """Кегль на странице с учётом уменьшения до поля набора 170 × 220 мм."""
    w, h = Image.open(path).size
    wpt, hpt = w * 72 / dpi, h * 72 / dpi
    k = min(1.0, TEXT_W / wpt, TEXT_H / hpt)
    report.append((os.path.basename(path), round(min_font * k, 1),
                   round(wpt * k / 72 * 25.4), round(hpt * k / 72 * 25.4)))


# ---------------------------------------------------------------- Graphviz

def gv_font_check():
    """Graphviz должен найти именно Times New Roman (обычный и полужирный)."""
    src = (f'digraph G {{ a [fontname="{GV_FONT}", label="Проверка"]; '
           f'b [fontname="{GV_FONT}", label=<<b>Полужирный</b>>]; }}')
    r = subprocess.run(["dot", "-v", "-Tpng", "-o", os.devnull],
                       input=src.encode("utf-8"), capture_output=True)
    resolved = [ln for ln in r.stderr.decode("utf-8", "replace").splitlines()
                if "resolved to" in ln]
    if r.returncode or not resolved or any("Times New Roman" not in ln
                                           for ln in resolved):
        sys.exit("Graphviz не нашёл Times New Roman: " + "; ".join(resolved))


def render(name, source, min_font=FS):
    path = os.path.join(OUT, name + ".png")
    with open(os.path.join(OUT, "src", name + ".dot"), "w", encoding="utf-8") as fh:
        fh.write(source)
    subprocess.run(["dot", "-Tpng", f"-Gdpi={DPI}", "-o", path],
                   input=source.encode("utf-8"), check=True)
    set_dpi(path, DPI)
    note(path, DPI, min_font)


def head(extra=""):
    return (f'digraph G {{\n graph [fontname="{GV_FONT}", bgcolor=white, fontsize={FS} {extra}];\n'
            f' node [fontname="{GV_FONT}", fontsize={FS}, color=black];\n'
            f' edge [fontname="{GV_FONT}", fontsize={FS}, color=black];\n')


# -------------------------------------------------------------- matplotlib

def mpl():
    """matplotlib с Times New Roman; без шрифта — ошибка, а не подмена."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in (TNR, TNR_BOLD):
        if not os.path.exists(f):
            sys.exit(f"нет шрифта {f}")
        font_manager.fontManager.addfont(f)
    plt.rcParams["font.family"] = FONT
    for weight, f in (("normal", TNR), ("bold", TNR_BOLD)):
        found = font_manager.findfont(font_manager.FontProperties(
            family=FONT, weight=weight), fallback_to_default=False)
        assert os.path.samefile(found, f), (weight, found)
    return plt


def check_fit(fig, ax, items, name):
    """items: (текст matplotlib, x0, x1) — текст не должен выходить за x0..x1."""
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    inv = ax.transData.inverted()
    for t, x0, x1 in items:
        bb = t.get_window_extent(renderer=r)
        (a, _), (b, _) = inv.transform([(bb.x0, bb.y0), (bb.x1, bb.y1)])
        if a < x0 - 1e-3 or b > x1 + 1e-3:
            overflow.append((name, t.get_text().replace("\n", " "),
                             round(a - x0, 3), round(x1 - b, 3)))


def page_axes(plt, width, height):
    """Рисунок в натуральную величину: 1 единица осей = 1 дюйм."""
    fig = plt.figure(figsize=(width, height))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, width)
    ax.set_ylim(-height, 0)
    ax.axis("off")
    return fig, ax


def save(fig, path, fsz):
    import matplotlib.pyplot as plt
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)
    set_dpi(path, DPI)
    note(path, DPI, fsz)


# --------------------------------------------------------------- ER-модель

# ключи и основные атрибуты; полный состав полей — в приложении А.
# В type_checks suggested_type_id выведен выше request_id: так линии связей
# с cert_types и requests не пересекаются.
ER_FIELDS = {
    "roles": ["id", "code"], "users": ["id", "login", "role_id"],
    "students": ["id", "user_id", "record_book_no", "group_code"],
    "cert_types": ["id", "code", "lead_days"], "statuses": ["id", "code"],
    "requests": ["id", "number", "student_id", "cert_type_id", "status_id",
                 "operator_id", "channel", "planned_date"],
    "status_history": ["id", "request_id", "changed_by", "from_status_id",
                       "to_status_id"],
    "type_checks": ["id", "suggested_type_id", "request_id"],
    "audit_log": ["id", "user_id", "action"]}
ER_TW, ER_HH, ER_RH = 1.8, 0.46, 0.24     # ширина таблицы, шапка, строка, дюймы
ER_X = {"A": 0.05, "B": 2.45, "C": 4.85}  # левые края трёх колонок
ER_POS = {  # колонка и верх таблицы, дюймы
    "users": ("B", -0.36),
    "roles": ("A", -0.36 - 2 * ER_RH),       # roles.id — напротив users.role_id
    "audit_log": ("C", -0.36 + ER_RH),       # audit_log.user_id — напротив users.id
    "cert_types": ("A", -2.11), "students": ("B", -2.11),
    "type_checks": ("C", -1.61),
    "statuses": ("A", -3.96), "requests": ("B", -3.96),
    "status_history": ("C", -3.96)}


def er_diagram(path):
    """ER-модель (ключи и основные атрибуты), ручная компоновка, matplotlib."""
    plt = mpl()
    import matplotlib.patheffects as pe
    from matplotlib.patches import Rectangle
    tables = db.metadata.tables
    assert set(ORDER) == set(tables) == set(ER_POS) == set(ER_FIELDS)
    fsz = MPL_FS
    fig, ax = page_axes(plt, PAGE_W, 6.75)
    rowy, fit = {}, []

    def X(name, side):
        return ER_X[ER_POS[name][0]] + (ER_TW if side == "r" else 0)

    for name, (col, y) in ER_POS.items():
        x = ER_X[col]
        fields = ER_FIELDS[name]
        h = ER_HH + ER_RH * len(fields)
        ax.add_patch(Rectangle((x, y - ER_HH), ER_TW, ER_HH, color="#e6e6e6", lw=0))
        ax.add_patch(Rectangle((x, y - h), ER_TW, h, fill=False, lw=1.1, zorder=3))
        ax.plot([x, x + ER_TW], [y - ER_HH] * 2, color="black", lw=0.8, zorder=3)
        for txt, yy, w in ((name, y - ER_HH * 0.3, "bold"),
                           (TITLES[name], y - ER_HH * 0.73, "normal")):
            t = ax.text(x + ER_TW / 2, yy, txt, ha="center", va="center",
                        fontsize=fsz, fontweight=w)
            fit.append((t, x, x + ER_TW))
        for i, f in enumerate(fields):
            c = tables[name].columns[f]
            key = "PK" if c.primary_key else ("FK" if c.foreign_keys else "")
            yy = y - ER_HH - ER_RH * (i + 0.5)
            rowy[(name, f)] = yy
            ax.text(x + 0.06, yy, key, fontsize=fsz, fontweight="bold", va="center")
            t = ax.text(x + 0.36, yy, f, fontsize=fsz, va="center")
            fit.append((t, x, x + ER_TW))

    drawn = {}
    halo = [pe.Stroke(linewidth=5, foreground="white"), pe.Normal()]

    def link(src, src_side, dst, dst_field, dst_side, lanes, bridge=False):
        """Линия от PK src к полю dst через вертикальные «полосы» lanes.

        lanes: [] — прямая; [x] — одна полоса; [x1, x2, y] — две полосы и
        горизонтальный переход по y. «Один» — поперечная черта, «много» —
        «воронья лапка»; уникальный внешний ключ (связь «один к одному») —
        черта и на стороне dst. bridge — белая подложка в местах пересечения
        с уже нарисованными линиями (линия проходит «поверх»)."""
        col = tables[dst].columns[dst_field]
        (fk,) = col.foreign_keys
        assert fk.column.table.name == src, (dst, dst_field)
        drawn[(dst, dst_field)] = src
        y0, y1 = rowy[(src, "id")], rowy[(dst, dst_field)]
        x0, x1 = X(src, src_side), X(dst, dst_side)
        pts = [(x0, y0)]
        if len(lanes) == 1:
            pts += [(lanes[0], y0), (lanes[0], y1)]
        elif len(lanes) == 3:
            pts += [(lanes[0], y0), (lanes[0], lanes[2]), (lanes[1], lanes[2]),
                    (lanes[1], y1)]
        else:
            assert abs(y0 - y1) < 1e-9, (src, dst)
        pts.append((x1, y1))
        xs, ys = zip(*pts)
        ax.plot(xs, ys, color="black", lw=1.0,
                path_effects=halo if bridge else None)
        d0 = 0.07 if src_side == "r" else -0.07
        ax.plot([x0 + d0] * 2, [y0 - 0.07, y0 + 0.07], color="black", lw=1.2)
        d1 = -0.13 if dst_side == "l" else 0.13
        if col.unique:
            ax.plot([x1 + d1 * 0.55] * 2, [y1 - 0.07, y1 + 0.07], color="black", lw=1.2)
        else:
            for dy in (-0.07, 0, 0.07):
                ax.plot([x1 + d1, x1], [y1, y1 + dy], color="black", lw=1.0)

    lu, lc, ls, lst = 4.4, 4.55, 2.33, 1.98   # полосы: users, cert/statuses, students, statuses
    lr, lct = 4.7, 2.15                        # полосы: requests, cert_types
    # горизонтальный переход cert_types → type_checks — между users и students
    gap = ((ER_POS["users"][1] - ER_HH - ER_RH * len(ER_FIELDS["users"]))
           + ER_POS["students"][1]) / 2
    bottom = ER_POS["requests"][1] - ER_HH - ER_RH * len(ER_FIELDS["requests"]) - 0.3
    link("roles", "r", "users", "role_id", "l", [])
    link("users", "r", "audit_log", "user_id", "l", [])
    link("users", "r", "students", "user_id", "r", [lu])
    link("users", "r", "requests", "operator_id", "r", [lu])
    link("users", "r", "status_history", "changed_by", "l", [lu])
    link("students", "l", "requests", "student_id", "l", [ls])
    link("cert_types", "r", "requests", "cert_type_id", "l", [lct])
    link("statuses", "r", "requests", "status_id", "l", [lst])
    link("statuses", "r", "status_history", "from_status_id", "l", [lst, lc, bottom])
    link("statuses", "r", "status_history", "to_status_id", "l", [lst, lc, bottom])
    link("requests", "r", "status_history", "request_id", "l", [lr], bridge=True)
    link("requests", "r", "type_checks", "request_id", "l", [lr], bridge=True)
    link("cert_types", "r", "type_checks", "suggested_type_id", "l",
         [lct, lc, gap], bridge=True)
    # точки ветвления общих линий (в отличие от пересечений)
    for x, key in ((lu, ("students", "user_id")), (lu, ("status_history", "changed_by")),
                   (lu, ("users", "id")), (lr, ("requests", "id")),
                   (lct, ("cert_types", "id")), (lst, ("requests", "status_id")),
                   (lc, ("status_history", "to_status_id"))):
        ax.plot([x], [rowy[key]], "ko", ms=3.2)
    fks = {(t, c.name) for t in tables for c in tables[t].columns if c.foreign_keys}
    assert set(drawn) == fks, sorted(fks ^ set(drawn))
    check_fit(fig, ax, fit, "ER")
    save(fig, path, fsz)
    with open(os.path.join(OUT, "src", "ris_2_05_er.tables"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(ER_POS))
    return len(tables), len(drawn)


# ------------------------------------------------- информационная модель

def info_model():
    tables = list(ORDER)
    assert set(tables) == set(db.metadata.tables)
    s = head(', rankdir=LR, nodesep=0.14, ranksep=0.5')
    s += ' node [shape=note, width=2.1];\n'
    inputs = {
        "in_login": "Учётные данные\\n(вход в систему)",
        "in_card": "Учётная запись,\\nкарточка студента",
        "in_cls": "Классификаторы:\\nроли, статусы",
        "in_types": "Справочник\\nтипов справок",
        "in_req": "Заявка студента\\n(канал АИС)",
        "in_ch": "Заявка из ЕЛК, МФСО,\\nот куратора",
        "in_dec": "Решение сотрудника:\\nстатус, причина отказа,\\nреквизиты справки-вызова",
        "in_tc": "Ответ локальной ИИ:\\nподходящие виды справок\\nдля цели заявки"}
    for k, v in inputs.items():
        s += f' {k} [label="{v}"];\n'
    s += (' subgraph cluster_db { label="База данных АИС"; style=rounded; color=black;\n'
          '  node [shape=cylinder, style=filled, fillcolor="#e6e6e6", width=1.9];\n')
    for t in tables:
        s += f'  t_{t} [label="{TITLES[t]}\\n({t})"];\n'
    s += ' }\n node [shape=note, style=solid, width=2.1];\n'
    outputs = {
        "out_cert": "Справка, справка-вызов\\n(печать, PDF)",
        "out_card": "Карточка заявки\\nс историей статусов",
        "out_reg": "Реестр заявок\\n(экран, CSV)",
        "out_hint": "Подсказка сотруднику\\n«вид ↔ цель»",
        "out_rep": "Отчёт за период\\n(экран, CSV)",
        "out_audit": "Журнал аудита"}
    for k, v in outputs.items():
        s += f' {k} [label="{v}"];\n'
    links = [("in_login", "users"), ("in_login", "audit_log"),
             ("in_card", "users"), ("in_card", "students"),
             ("in_cls", "roles"), ("in_cls", "statuses"),
             ("in_types", "cert_types"),
             ("in_req", "requests"), ("in_req", "status_history"),
             ("in_ch", "requests"), ("in_ch", "status_history"),
             ("in_dec", "requests"), ("in_dec", "status_history"),
             ("in_tc", "type_checks"),
             ("students", "out_cert"), ("requests", "out_cert"),
             ("cert_types", "out_cert"),
             ("requests", "out_card"), ("status_history", "out_card"),
             ("requests", "out_reg"), ("students", "out_reg"),
             ("type_checks", "out_hint"),
             ("requests", "out_rep"), ("cert_types", "out_rep"),
             ("statuses", "out_rep"), ("audit_log", "out_audit")]
    used = set()
    for a, b in links:
        for x in (a, b):
            if not x.startswith(("in_", "out_")):
                used.add(x)
        a = a if a.startswith(("in_", "out_")) else "t_" + a
        b = b if b.startswith(("in_", "out_")) else "t_" + b
        s += f' {a} -> {b};\n'
    assert used == set(tables), set(tables) - used
    return s + "}\n", len(tables)


LIFECYCLE = head(', rankdir=TB, nodesep=0.18, ranksep=0.45, forcelabels=true') + r'''
 node [shape=box, style=rounded];
 init [label="1. Инициация\n(ТЗ по ГОСТ 34.602)"];
 subgraph cluster_it { label="Инкременты 1–3"; style=dashed; color=black;
   an [label="2. Анализ"]; des [label="3. Проекти-\nрование"];
   imp [label="4. Реали-\nзация"]; tst [label="5. Тести-\nрование"];
   {rank=same; an; des; imp; tst;}
   an -> des -> imp -> tst;
   tst -> an [xlabel="следующий инкремент", style=dashed, constraint=false]; }
 dep [label="6. Внедрение\n(опытная\nэксплуатация)"]; ops [label="7. Сопро-\nвождение"];
 {rank=same; dep; ops;}
 init -> an; tst -> dep; dep -> ops;
}
'''


# ------------------------------------------------------------ дерево функций

ROOT_TITLE = "АИС учёта заявок студентов на получение справок"
FUNC_TREE = [
    ("1. Доступ\nи безопасность", [
        "1.1 Вход\nпо логину\nи паролю",
        "1.2 Блокировка\nна 15 мин после\n5 ошибок",
        "1.3 Доступ\nпо ролям",
        "1.4 Смена\nпароля, выход"]),
    ("2. Кабинет\nстудента", [
        "2.1 Подача\nзаявки",
        "2.2 Расчёт\nплановой даты\nготовности",
        "2.3 Заявки\nи история\nстатусов",
        "2.4 Отмена\nновой заявки",
        "2.5 Справка\nв PDF"]),
    ("3. Обработка\nзаявок", [
        "3.1 Реестр,\nотбор по\nстатусу, каналу",
        "3.2 Регистрация\nиз ЕЛК, МФСО,\nот куратора",
        "3.3 Разбор\nобращения\nлокальной ИИ",
        "3.4 Подсказка\n«вид ↔ цель»",
        "3.5 Смена\nстатуса,\nотклонение",
        "3.6 Реквизиты\nсправки-вызова",
        "3.7 Печать\nсправок, PDF"]),
    ("4. Отчётность", [
        "4.1 Сроки\nобработки,\nдоля в срок",
        "4.2 Сводка\nпо типам\nи статусам",
        "4.3 Сводка\nпо каналам",
        "4.4 Контроль\nпросроченных\nзаявок",
        "4.5 Экспорт\nв CSV"]),
    ("5. Администри-\nрование", [
        "5.1 Справочник\nтипов справок",
        "5.2 Учётные\nзаписи,\nкарточки\nстудентов",
        "5.3 Блокировка\nучётных\nзаписей",
        "5.4 Журнал\nаудита",
        "5.5 Резервное\nкопирование БД"]),
]


def functions_tree(path):
    """Дерево функций: корень, пять групп, функции «гребёнкой» под группой."""
    plt = mpl()
    from matplotlib.patches import Rectangle
    fsz = MPL_FS
    lh = fsz * 1.2 / 72            # высота строки, дюймы
    pad, padx, vgap, comb = 0.06, 0.05, 0.09, 0.1
    n = len(FUNC_TREE)
    gapx = 0.05
    colw = (PAGE_W - 0.04 - gapx * (n - 1)) / n

    def bh(text):
        return (text.count("\n") + 1) * lh + 2 * pad

    root_h = bh(ROOT_TITLE)
    grp_h = max(bh(g) for g, _ in FUNC_TREE)
    y_root = -0.04
    y_bus = y_root - root_h - 0.17
    y_grp = y_bus - 0.17
    heights = [sum(bh(f) + vgap for f in leaves) for _, leaves in FUNC_TREE]
    total_h = -y_grp + grp_h + 0.12 + max(heights) + 0.05
    fig, ax = page_axes(plt, PAGE_W, total_h)
    fit = []

    def box(x, y, w, h, text, bold=False, fill="white", align="center"):
        """Блок с текстом; строки ставятся по базовой линии с равным шагом lh
        (у многострочного текста matplotlib интервал зависит от букв)."""
        ax.add_patch(Rectangle((x, y - h), w, h, facecolor=fill, edgecolor="black", lw=1.0))
        tx = x + w / 2 if align == "center" else x + padx
        lines = text.split("\n")
        top = y - (h - len(lines) * lh) / 2
        for i, ln in enumerate(lines):
            t = ax.text(tx, top - (i + 1) * lh + 0.28 * lh, ln, ha=align,
                        va="baseline", fontsize=fsz,
                        fontweight="bold" if bold else "normal")
            fit.append((t, x + 0.02, x + w - 0.02))

    rw = 4.2
    box((PAGE_W - rw) / 2, y_root, rw, root_h, ROOT_TITLE, bold=True, fill="#e6e6e6")
    ax.plot([PAGE_W / 2] * 2, [y_root - root_h, y_bus], color="black", lw=1.0)
    xs = [0.02 + i * (colw + gapx) for i in range(n)]
    ax.plot([xs[0] + colw / 2, xs[-1] + colw / 2], [y_bus] * 2, color="black", lw=1.0)
    for x, (title, leaves) in zip(xs, FUNC_TREE):
        ax.plot([x + colw / 2] * 2, [y_bus, y_grp], color="black", lw=1.0)
        box(x, y_grp, colw, grp_h, title, bold=True, fill="#e6e6e6")
        y = y_grp - grp_h - 0.12
        cx = x + comb / 2
        mids = []
        for leaf in leaves:
            h = bh(leaf)
            box(x + comb, y, colw - comb, h, leaf, align="left")
            mids.append(y - h / 2)
            ax.plot([cx, x + comb], [y - h / 2] * 2, color="black", lw=1.0)
            y -= h + vgap
        ax.plot([cx, cx], [y_grp - grp_h, mids[-1]], color="black", lw=1.0)
    check_fit(fig, ax, fit, "functions")
    save(fig, path, fsz)
    return sum(len(leaves) for _, leaves in FUNC_TREE)


DIALOG = head(', rankdir=TB, nodesep=0.14, ranksep=0.24') + r'''
 node [shape=box, style=rounded];
 login [label="Вход в систему", style="rounded,filled", fillcolor="#e6e6e6"];
 chk [shape=diamond, style=solid, label="Логин и пароль\nверны?", height=0.8];
 role [shape=diamond, style=solid, label="Роль"];
 login -> chk; chk:w -> login:w [label="нет "];
 chk -> role [label=" да"];
 s1 [label="Личный кабинет"]; s2 [label="Форма заявки"]; s4 [label="Мои заявки"];
 s3 [label="Карточка заявки\n(отмена, PDF)"];
 o1 [label="Реестр заявок\n(отбор, CSV)"];
 o5 [label="Регистрация заявки\nиз ЕЛК, МФСО,\nот куратора"];
 o6 [label="Разбор текста\nобращения\nлокальной ИИ"];
 o2 [label="Обработка заявки\n(статус, подсказка ИИ,\nреквизиты справки-вызова)"];
 o3 [label="Печатная форма\nсправки, PDF"]; o4 [label="Отчёты, CSV"];
 a1 [label="Типы справок,\nпользователи,\nжурнал аудита"];
 role -> s1 [label="студент "]; role -> o1 [label=" сотрудник,\l администратор\l"];
 s1 -> s2 -> s3; s1 -> s4 -> s3;
 o1 -> o5; o5 -> o6 [dir=both, label=" текст /\l поля\l"];
 o5 -> o2; o1 -> o2; o2 -> o3;
 o1 -> o4; o1 -> a1 [label=" админ."];
 out [label="Выход", style="rounded,filled", fillcolor="#e6e6e6"];
 s3 -> out [style=dashed, constraint=false]; o3 -> out [style=dashed];
 o4 -> out [style=dashed, constraint=false]; a1 -> out [style=dashed, constraint=false];
}
'''


# ------------------------------------- дерево вызова программных модулей

MODULE_FILES = {
    "run": "run.py", "init": "app/__init__.py", "auth": "app/views/auth.py",
    "stud": "app/views/student.py", "staff": "app/views/staff.py",
    "adm": "app/views/admin.py", "forms": "app/forms.py", "sec": "app/security.py",
    "svc": "app/services.py", "rep": "app/reports.py", "cert": "app/certificate.py",
    "llm": "app/llm.py", "tc": "app/type_check.py", "wd": "app/workdays.py",
    "cfg": "app/config.py", "models": "app/models.py"}
VIEWS = ("auth", "stud", "staff", "adm")
# узел рисунка: подпись (первая строка — файл) и функции модуля, которые
# вызываются из других модулей (сверяется с кодом в module_calls())
MODULE_NODES = {
    "run": ("run.py", []),
    "init": ("__init__.py: create_app;\nкоманды flask check-types,\nbackup-db, init-db", []),
    "auth": ("auth.py\nвход", []),
    "stud": ("student.py\nстудент", []),
    "staff": ("staff.py\nсотрудник", []),
    "adm": ("admin.py\nадминистратор", []),
    "tc": ("type_check.py", ["run_type_checks"]),
    "forms": ("forms.py\nформы ввода", []),
    "sec": ("security.py", ["authenticate", "role_required", "audit"]),
    "svc": ("services.py", ["create_request", "change_status", "allowed_targets",
                            "save_vyzov", "dative_name", "is_female"]),
    "rep": ("reports.py", ["registry_query", "registry_rows", "statistics",
                           "to_csv"]),
    "cert": ("certificate.py", ["certificate_text", "certificate_pdf"]),
    "llm": ("llm.py", ["parse_appeal", "clean_suggestion", "check_type",
                       "type_verdict"]),
    "wd": ("workdays.py", ["planned_date", "workdays_between"]),
}


def _resolve(path, node):
    """Файл модуля для `from … import …` внутри пакета app (или None)."""
    if node.level == 0:
        return None
    base = os.path.dirname(path)
    for _ in range(node.level - 1):
        base = os.path.dirname(base)
    if node.module:
        p = os.path.join(base, *node.module.split("."))
        return p + ".py" if os.path.exists(os.path.join(ROOT, p + ".py")) \
            else os.path.join(p, "__init__.py")
    return base  # from . import llm — имена являются модулями


def module_calls():
    """Вызовы между модулями: {модуль: {модуль: {имена}}} по исходному коду.

    Учитываются вызовы функций и создание объектов классов, импортированных
    из других модулей app (в том числе `llm.parse_appeal(...)` после
    `from . import llm`), и декораторы. Импорт констант вызовом не считается.
    """
    by_file = {v: k for k, v in MODULE_FILES.items()}
    by_file["app/__init__.py"] = "init"
    calls = {}
    for key, path in MODULE_FILES.items():
        tree = ast.parse(open(os.path.join(ROOT, path), encoding="utf-8").read())
        names, mods = {}, {}
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                if n.level == 0 and n.module == "app":   # run.py
                    for a in n.names:
                        names[a.asname or a.name] = ("init", a.name)
                    continue
                target = _resolve(path, n)
                if target is None:
                    continue
                for a in n.names:
                    if n.module is None:
                        mods[a.asname or a.name] = by_file.get(
                            os.path.join(target, a.name + ".py"))
                    elif target in by_file:
                        names[a.asname or a.name] = (by_file[target], a.name)
        out = {}
        for n in ast.walk(tree):
            f = n.func if isinstance(n, ast.Call) else None
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in n.decorator_list:
                    if isinstance(d, ast.Name) and d.id in names:
                        m, nm = names[d.id]
                        out.setdefault(m, set()).add(nm)
            if isinstance(f, ast.Name) and f.id in names:
                m, nm = names[f.id]
                out.setdefault(m, set()).add(nm)
            elif (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                  and mods.get(f.value.id)):
                out.setdefault(mods[f.value.id], set()).add(f.attr)
        calls[key] = out
    return calls


def modules_dot():
    """Рисунок 2.6: дерево вызова модулей; стрелка — вызов функций модуля."""
    calls = module_calls()
    edges = {(a, b) for a, dst in calls.items() for b in dst
             if b not in ("models", "cfg") and a != b}
    # подписи узлов: перечисленные функции вызываются из других модулей
    called = {}
    for a, dst in calls.items():
        for b, nms in dst.items():
            if a != b:
                called.setdefault(b, set()).update(nms)
    for key, (_, funcs) in MODULE_NODES.items():
        assert set(funcs) <= called.get(key, set()), (key, set(funcs) - called.get(key, set()))
    # модели и БД: к ним обращаются модули, импортирующие из models.py классы
    # моделей или объект db (не только константы классификаторов)
    mtree = ast.parse(open(os.path.join(ROOT, MODULE_FILES["models"]), encoding="utf-8").read())
    model_objs = {n.name for n in mtree.body if isinstance(n, ast.ClassDef)} | {"db"}
    db_users = []
    for key, path in MODULE_FILES.items():
        tree = ast.parse(open(os.path.join(ROOT, path), encoding="utf-8").read())
        if any(isinstance(n, ast.ImportFrom) and n.module and n.module.endswith("models")
               and {a.name for a in n.names} & model_objs for n in ast.walk(tree)):
            db_users.append(key)
    text = open(os.path.join(ROOT, "app/__init__.py"), encoding="utf-8").read()
    # модули представления регистрирует create_app (импорт внутри функции)
    for v in VIEWS:
        mod = MODULE_FILES[v].replace("app/", ".").replace("/", ".")[:-3]
        assert f"from {mod} import bp" in text, mod
    common = {"forms", "sec"}
    for v in VIEWS:
        assert common <= {b for (a, b) in edges if a == v}, v
    drawn = {("run", "init"), ("init", "tc"), ("init", "sec"),
             ("stud", "svc"), ("stud", "cert"),
             ("staff", "svc"), ("staff", "rep"), ("staff", "cert"), ("staff", "llm"),
             ("tc", "llm"), ("svc", "wd"), ("svc", "sec"), ("rep", "wd"),
             ("cert", "svc")}
    drawn |= {(v, b) for v in VIEWS for b in common}
    assert drawn == edges, ("рисунок ≠ код", sorted(drawn ^ edges))

    def label(key):
        title, funcs = MODULE_NODES[key]
        lines = [title]
        line = ""
        for f in funcs:
            item = f + ","
            if line and len(line) + len(item) > 22:
                lines.append(line)
                line = ""
            line = (line + " " + item).strip()
        if line:
            lines.append(line)
        return "\\n".join(lines).rstrip(",")

    users = {"init": "create_app", "auth": "auth", "stud": "student",
             "staff": "staff", "adm": "admin", "svc": "services",
             "rep": "reports", "sec": "security", "tc": "type_check"}
    names = [users[a] for a in db_users if a in users]
    who = ", ".join(names[:5]) + ",\\n" + ", ".join(names[5:])
    assert set(db_users) <= set(users), db_users
    s = head(', rankdir=TB, nodesep=0.18, ranksep=0.36, compound=true') + ' node [shape=box];\n'
    s += ' run [label="run.py", style=filled, fillcolor="#e6e6e6"];\n'
    s += f' init [label="{label("init")}", style=filled, fillcolor="#e6e6e6"];\n'
    s += (' subgraph cluster_views { label="модули представления app/views (blueprints)";'
          ' style=dashed; color=black;\n')
    for v in VIEWS:
        s += f'  {v} [label="{label(v)}"];\n'
    s += ' }\n'
    for k in ("tc", "forms", "sec", "svc", "rep", "cert", "llm", "wd"):
        s += f' {k} [label="{label(k)}"];\n'
    s += ' ext [label="llama-server\\n(локальная модель\\nна сервере вуза)", style=dashed];\n'
    s += (f' models [label="models.py — классы моделей SQLAlchemy\\n'
          f'→ БД SQLite (9 таблиц); к ним обращаются\\n{who}", '
          'style=filled, fillcolor="#e6e6e6"];\n')
    s += ' {rank=same; run; init;}\n wd -> models [style=invis]; sec -> models [style=invis];\n'
    s += ' init -> stud [lhead=cluster_views, label=" маршруты"];\n'
    s += ' init -> tc [label=" check-types"];\n'
    s += ' adm -> sec [ltail=cluster_views]; auth -> forms [ltail=cluster_views];\n'
    s += ' llm -> ext [label=" HTTP, JSON", style=dashed];\n'
    for a, b in sorted(drawn):
        if (a in VIEWS and b in common) or (a, b) == ("init", "tc"):
            continue
        s += f' {a} -> {b};\n'
    return s + "}\n", len(drawn)


# ------------------------------------------------------------ блок-схема

def flowchart(path):
    """Блок-схема planned_date() по ГОСТ 19.701-90 (matplotlib)."""
    plt = mpl()
    from matplotlib.patches import FancyBboxPatch, Polygon, Rectangle
    fsz = MPL_FS
    fig, ax = plt.subplots(figsize=(6.6, 8.6))
    ax.set_xlim(-3.0, 6.2)
    ax.set_ylim(-12.3, 0.5)
    ax.axis("off")
    W, H = 3.3, 0.66
    kw = dict(fill=False, lw=1.2, ec="black")

    def text(x, y, t):
        ax.text(x, y, t, ha="center", va="center", fontsize=fsz)

    def term(x, y, t):
        ax.add_patch(FancyBboxPatch((x - W / 2 + .5, y - H / 2), W - 1.0, H,
                                    boxstyle="round,pad=0,rounding_size=0.3", **kw))
        text(x, y, t)

    def proc(x, y, t):
        ax.add_patch(Rectangle((x - W / 2, y - H / 2), W, H, **kw))
        text(x, y, t)

    def data(x, y, t):
        d, w2 = 0.25, W / 2 + 0.25
        ax.add_patch(Polygon([(x - w2 + d, y + H / 2), (x + w2 + d, y + H / 2),
                              (x + w2 - d, y - H / 2), (x - w2 - d, y - H / 2)], **kw))
        text(x, y, t)

    def dec(x, y, t):
        ax.add_patch(Polygon([(x, y + .6), (x + 2.0, y), (x, y - .6), (x - 2.0, y)], **kw))
        text(x, y, t)

    def line(pts, arrow=True, label=None, lpos=None):
        xs, ys = zip(*pts)
        ax.plot(xs, ys, color="black", lw=1.1)
        if arrow:
            ax.annotate("", xy=pts[-1], xytext=pts[-2],
                        arrowprops=dict(arrowstyle="-|>", color="black", lw=1.1,
                                        shrinkA=0, shrinkB=0))
        if label:
            ax.text(*lpos, label, fontsize=fsz - 1, ha="left", va="bottom")

    X2 = 4.0
    term(0, 0, "Начало")
    data(0, -1.05, "created_at, lead_days,\nHOLIDAYS")
    dec(0, -2.2, "Час подачи\n≥ 17:00?")
    proc(X2, -2.2, "base := дата\nподачи + 1 день")
    proc(0, -3.3, "base := дата подачи")
    dec(0, -4.75, "base —\nрабочий день?")
    proc(X2, -4.75, "base := base + 1")
    proc(0, -6.0, "day := base;\nleft := lead_days")
    dec(0, -7.25, "left > 0?")
    proc(0, -8.5, "day := day + 1")
    dec(0, -9.75, "day —\nрабочий день?")
    proc(0, -11.0, "left := left − 1")
    data(X2, -9.75, "planned_date := day")
    term(X2, -11.0, "Конец")
    line([(0, -.33), (0, -.72)])
    line([(0, -1.38), (0, -1.6)])
    line([(2.0, -2.2), (X2 - W / 2, -2.2)], label="да", lpos=(1.95, -2.18))
    line([(0, -2.8), (0, -2.97)], label="нет", lpos=(.08, -2.95))
    line([(0, -3.63), (0, -4.15)])
    line([(X2, -2.53), (X2, -3.85), (0, -3.85)])
    line([(2.0, -4.75), (X2 - W / 2, -4.75)], label="нет", lpos=(1.95, -4.73))
    line([(X2, -4.42), (X2, -4.05), (0, -4.05)])
    line([(0, -5.35), (0, -5.67)], label="да", lpos=(.08, -5.6))
    line([(0, -6.33), (0, -6.65)])
    line([(0, -7.85), (0, -8.17)], label="да", lpos=(.08, -8.1))
    line([(0, -8.83), (0, -9.15)])
    line([(0, -10.35), (0, -10.67)], label="да", lpos=(.08, -10.6))
    line([(0, -11.33), (0, -11.75), (-2.5, -11.75), (-2.5, -6.5), (0, -6.5)])
    line([(-2.0, -9.75), (-2.5, -9.75)], arrow=False, label="нет", lpos=(-2.45, -9.73))
    ax.plot([-2.5], [-9.75], "ko", ms=3.5)
    line([(2.0, -7.25), (X2, -7.25), (X2, -9.42)], label="нет", lpos=(2.05, -7.23))
    line([(X2, -10.08), (X2, -10.67)])
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    set_dpi(path, DPI)
    note(path, DPI, fsz - 1)   # подписи «да»/«нет» на 1 пт мельче блоков


def main():
    os.makedirs(os.path.join(OUT, "src"), exist_ok=True)
    gv_font_check()
    n_er, n_links = er_diagram(os.path.join(OUT, "ris_2_05_er.png"))
    im, n_im = info_model()
    render("ris_2_01_lifecycle", LIFECYCLE)
    render("ris_2_02_infomodel", im)
    n_func = functions_tree(os.path.join(OUT, "ris_2_03_functions.png"))
    render("ris_2_04_dialog", DIALOG)
    mod_dot, n_calls = modules_dot()
    render("ris_2_06_modules", mod_dot)
    flowchart(os.path.join(OUT, "ris_2_07_flowchart.png"))
    shots = os.path.join(ROOT, "screenshots")
    for name in sorted(os.listdir(shots)):
        if name.endswith(".png"):
            dst = os.path.join(OUT, "scr_" + name)
            shutil.copy(os.path.join(shots, name), dst)
            set_dpi(dst, SHOT_DPI)
            note(dst, SHOT_DPI, 14 * 0.75)   # основной текст интерфейса 14 px
    print(f"таблиц в ER: {n_er} (связей {n_links}), в информационной модели: {n_im}")
    print(f"функций в дереве: {n_func}; связей вызова в дереве модулей: {n_calls}")
    print("рисунок | кегль на странице, пт | ширина × высота на странице, мм")
    bad = []
    for name, pt, w, h in report:
        print(f"  {name}: {pt} пт, {w}×{h} мм")
        if pt < 10 and not name.startswith("scr_"):
            bad.append(name)
    for item in overflow:
        print("  текст за рамкой:", item)
    if bad or overflow:
        sys.exit(f"кегль < 10 пт: {bad}; текст за рамкой: {len(overflow)}")


if __name__ == "__main__":
    main()
