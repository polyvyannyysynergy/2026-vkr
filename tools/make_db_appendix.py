"""Сборка «Приложение А. Структура таблиц базы данных» из метаданных моделей.

Запуск: python tools/make_db_appendix.py [файл_вывода]
Типы, ключи и обязательность полей берутся из app/models.py (SQLAlchemy),
описания полей — из словаря D ниже (проверяется полнота: новая таблица или
новое поле без описания останавливают сборку).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.models import db  # noqa: E402

VKR = os.path.join(os.path.dirname(ROOT), "03_Текст ВКР_до 2026-10-28")
if os.path.isdir(os.path.join(VKR, "_рабочие_файлы", "parts")):
    VKR = os.path.join(VKR, "_рабочие_файлы")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    VKR, "parts", "prilozhenie_bd.md")
ORDER = ["roles", "users", "students", "cert_types", "statuses", "requests",
         "status_history", "type_checks", "audit_log"]
NUM_WORDS = {8: "восьми", 9: "девяти", 10: "десяти", 11: "одиннадцати"}
D = {
"roles": ("Роли", {"id":"Идентификатор роли","code":"Код роли (STUDENT, STAFF, ADMIN)","name":"Наименование роли"}),
"users": ("Пользователи", {"id":"Идентификатор пользователя","login":"Логин для входа, уникален","password_hash":"Хеш пароля (scrypt, werkzeug.security)","full_name":"Фамилия, имя, отчество","email":"Адрес электронной почты","role_id":"Ссылка на роль (roles.id)","is_active":"Признак активной учётной записи (снимается при блокировке администратором)","failed_logins":"Счётчик неудачных попыток входа","locked_until":"Окончание временной блокировки после неудачных попыток","created_at":"Дата и время создания записи","last_login_at":"Дата и время последнего входа"}),
"students": ("Студенты", {"id":"Идентификатор карточки студента","user_id":"Ссылка на учётную запись (users.id), 1:1","record_book_no":"Номер зачётной книжки, уникален","birth_date":"Дата рождения","faculty":"Факультет","direction":"Код и наименование направления подготовки","group_code":"Код учебной группы","course":"Курс (1–6)","study_form":"Код формы обучения (OCH, OZ, ZAO)","funding":"Код основы обучения (BUD, DOG)","enroll_order":"Номер приказа о зачислении","enroll_date":"Дата зачисления","graduation_date":"Нормативная дата окончания обучения"}),
"cert_types": ("Типы справок", {"id":"Идентификатор типа справки","code":"Мнемокод типа (OB, VK, VYZ, …)","name":"Наименование справки","lead_days":"Нормативный срок изготовления, рабочих дней","max_copies":"Максимум экземпляров в одной заявке","printable":"Формируется по шаблону АИС (печать, PDF); иначе — бланк вне системы","electronic":"Допускается выдача электронно (PDF в кабинете студента)","description":"Пояснение к типу справки (выводится в справочнике и передаётся локальной модели в перечне видов)","is_active":"Доступна для заказа","sort_order":"Порядок вывода в списках"}),
"statuses": ("Статусы заявок", {"id":"Идентификатор статуса","code":"Код статуса (NEW, PREP, …)","name":"Наименование статуса","is_final":"Признак завершающего статуса","css":"Цвет отметки статуса в интерфейсе","sort_order":"Порядок вывода"}),
"requests": ("Заявки", {"id":"Идентификатор заявки","number":"Номер заявки ГГГГ-NNNNN, уникален","student_id":"Ссылка на студента (students.id)","cert_type_id":"Ссылка на тип справки (cert_types.id)","status_id":"Ссылка на текущий статус (statuses.id)","operator_id":"Ссылка на исполнителя (users.id)","purpose":"Место предоставления (цель) справки; для справки-вызова — работодатель","copies":"Количество экземпляров","delivery":"Код способа получения (EL, DEAN, POST)","post_address":"Почтовый адрес (для POST)","student_comment":"Комментарий студента или сотрудника, зарегистрировавшего заявку","channel":"Код канала поступления (AIS, ELK, MFSO, KUR)","ext_number":"Номер заявки во внешнем канале (например, в ЕЛК)","name_dat":"ФИО студента в дательном падеже (справка-вызов)","basis":"Код основания справки-вызова (PA, GIA, VKR, GEX)","period_from":"Начало периода справки-вызова","period_to":"Окончание периода справки-вызова","reject_reason":"Причина отклонения","created_at":"Дата и время подачи (регистрации)","planned_date":"Плановая дата готовности (расчётная)","ready_at":"Фактическое время готовности","closed_at":"Время перевода в завершающий статус"}),
"status_history": ("История статусов", {"id":"Идентификатор записи","request_id":"Ссылка на заявку (requests.id)","from_status_id":"Предыдущий статус (statuses.id), пусто при подаче","to_status_id":"Новый статус (statuses.id)","changed_by":"Автор изменения (users.id)","changed_at":"Дата и время изменения","comment":"Комментарий или причина"}),
"type_checks": ("Проверки типа справки", {"id":"Идентификатор записи проверки","request_id":"Ссылка на заявку (requests.id), 1:1","suggested_type_id":"Тип справки, который по цели заявки предложила локальная модель (cert_types.id); пусто — выбранный тип подходит","checked_at":"Дата и время проверки","model":"Обозначение модели, выполнившей проверку"}),
"audit_log": ("Журнал аудита", {"id":"Идентификатор события","user_id":"Пользователь (users.id), пусто для анонимного и для команд по расписанию","action":"Код события (LOGIN, STATUS_CHANGE, LLM_PARSE, …)","entity":"Тип объекта (request, user, …)","entity_id":"Идентификатор объекта","details":"Подробности события (без паролей и текста обращений)","ip":"IP-адрес клиента","created_at":"Дата и время события"}),
}


def main():
    assert set(ORDER) == set(db.metadata.tables), (
        "состав таблиц изменился: добавьте таблицу в ORDER и D",
        sorted(set(db.metadata.tables) ^ set(ORDER)))
    n = len(ORDER)
    out = ["# Приложение А. Структура таблиц базы данных АИС «Справки»", "",
           f"В приложении приведена структура записей {NUM_WORDS[n]} таблиц базы "
           "данных (ER-модель приведена в п. 2.3.2). Обозначения: PK — первичный "
           "ключ, FK — внешний ключ с указанием таблицы, на которую он ссылается, "
           "UQ — уникальный ключ; «Обяз.» — поле не допускает пустого значения.", ""]
    for i, name in enumerate(ORDER, 1):
        t = db.metadata.tables[name]
        title, desc = D[name]
        assert set(desc) == {c.name for c in t.columns}, (
            name, sorted(set(desc) ^ {c.name for c in t.columns}))
        out += [f"Таблица А.{i} – Структура таблицы {name} («{title}»)", "",
                "| Поле | Тип | Ключ | Обяз. | Описание |", "|---|---|---|---|---|"]
        for c in t.columns:
            if c.primary_key:
                key = "PK"
            elif c.foreign_keys:
                key = "FK → " + next(iter(c.foreign_keys)).column.table.name
                if c.unique:  # уникальный внешний ключ — связь «один к одному»
                    key += ", UQ"
            else:
                key = "UQ" if c.unique else ""
            need = "да" if (not c.nullable or c.primary_key) else "нет"
            out.append(f"| {c.name} | {c.type} | {key} | {need} | {desc[c.name]} |")
        out += ["", "Источник: разработано автором", ""]
    idx = []
    for name in ORDER:
        for ix in sorted(db.metadata.tables[name].indexes, key=lambda i: i.name):
            cols = ", ".join(c.name for c in ix.columns)
            idx.append(f"{name}.{cols}" + (" (уникальный)" if ix.unique else ""))
    out += ["Индексы базы данных (помимо первичных ключей и ограничений UQ, указанных "
            f"в таблицах А.1–А.{n}): " + "; ".join(idx) + ". Уникальные индексы "
            "исключают повтор логина и номера заявки и ускоряют вход по логину, "
            "остальные — выборку заявок студента, отбор реестра по статусу, каналу "
            "поступления и группе, вывод истории заявки и отбор журнала аудита по "
            "коду события.", ""]
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    print(f"{OUT}: таблиц {n}, полей {sum(len(D[t][1]) for t in ORDER)}")


if __name__ == "__main__":
    main()
