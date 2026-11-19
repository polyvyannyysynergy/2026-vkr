"""Конфигурация АИС учёта заявок на справки.

Значения по умолчанию рассчитаны на локальный запуск. Для эксплуатации
SECRET_KEY (иначе — случайный ключ в instance/secret.key) и путь к БД
задаются переменными окружения AIS_SECRET_KEY и
AIS_DATABASE; строка подключения к другой СУБД (например, PostgreSQL) —
переменной AIS_DATABASE_URL. Адрес локальной языковой модели для разбора
обращений — AIS_LLM_URL (пусто — функция выключена).
"""
import os
from datetime import date, timedelta

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


# Производственный календарь (пятидневная неделя). Источники:
# ст. 112 ТК РФ; постановление Правительства РФ от 24.09.2025 № 1466
# (переносы 2026 г.); постановление Правительства РФ от 17.09.2026 № 1187
# (переносы 2027 г.). Праздник, совпавший с выходным (кроме январских),
# переносит выходной на следующий рабочий день (ч. 2 ст. 112 ТК РФ) —
# считается функцией weekend_holiday_transfers на любой год.
FIXED_HOLIDAYS = [(1, d) for d in range(1, 9)] + [
    (2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4)]
TRANSFERRED_DAYS_OFF = {
    2026: ["2026-01-09", "2026-03-09", "2026-05-11", "2026-12-31"],
    2027: ["2027-02-22", "2027-05-03", "2027-05-10", "2027-06-14",
           "2027-11-05", "2027-12-31"],
}
# субботы и воскресенья, объявленные рабочими днями при переносе
WORKING_WEEKENDS = frozenset({date(2027, 2, 20)})
# праздники ст. 112 ТК РФ — на каждый год диапазона; переносы следующих лет
# (постановления Правительства РФ выходят осенью) — переменной AIS_EXTRA_HOLIDAYS
HOLIDAY_YEARS = range(2026, 2041)


def weekend_holiday_transfers(year):
    """Выходные, перенесённые по ч. 2 ст. 112 ТК РФ: праздник, совпавший с
    субботой или воскресеньем, делает нерабочим следующий рабочий день.

    Январские праздники так не переносятся: два из них Правительство РФ
    переносит постановлением на другие даты (TRANSFERRED_DAYS_OFF,
    AIS_EXTRA_HOLIDAYS).
    """
    fixed = {date(year, m, d) for m, d in FIXED_HOLIDAYS}
    moved = set()
    for day in sorted(fixed):
        if day.month == 1 or day.weekday() < 5:
            continue
        nxt = day + timedelta(days=1)
        while nxt.weekday() >= 5 or nxt in fixed or nxt in moved:
            nxt += timedelta(days=1)
        moved.add(nxt)
    return moved


def _holidays():
    """Нерабочие дни 2026–2040 гг.: праздники и их переносы с выходных по
    ч. 2 ст. 112 ТК РФ; переносы январских праздников 2026–2027 гг. — по
    постановлениям.

    Переносы январских праздников следующих лет задаются переменной
    AIS_EXTRA_HOLIDAYS: ГГГГ-ММ-ДД через запятую.
    """
    days = {date(y, m, d) for y in HOLIDAY_YEARS for m, d in FIXED_HOLIDAYS}
    for year in HOLIDAY_YEARS:
        days |= weekend_holiday_transfers(year)
    for items in TRANSFERRED_DAYS_OFF.values():
        days.update(date.fromisoformat(d) for d in items)
    extra = os.environ.get("AIS_EXTRA_HOLIDAYS", "")
    for item in filter(None, (s.strip() for s in extra.split(","))):
        days.add(date.fromisoformat(item))
    return frozenset(days)


class Config:
    # без AIS_SECRET_KEY фабрика приложения создаёт случайный ключ в instance/secret.key
    SECRET_KEY = os.environ.get("AIS_SECRET_KEY")
    # AIS_DATABASE_URL — полная строка подключения SQLAlchemy
    # (postgresql+psycopg://user:pass@host/ais); иначе — файл SQLite
    SQLALCHEMY_DATABASE_URI = os.environ.get("AIS_DATABASE_URL") or (
        "sqlite:///" + os.environ.get(
            "AIS_DATABASE", os.path.join(INSTANCE_DIR, "ais.sqlite3")))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("AIS_HTTPS", "0") == "1"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8  # рабочая смена, секунд
    HOLIDAYS = _holidays()
    MAX_FAILED_LOGINS = 5          # попыток до временной блокировки
    LOCK_MINUTES = 15              # длительность блокировки
    PAGE_SIZE = 20                 # строк реестра на странице
    ORG_NAME = "Университет «Синергия»"
    ORG_NAME_GEN = "Университета «Синергия»"  # родительный падеж для справки
    ORG_NAME_PREP = "Университете «Синергия»"  # предложный падеж (справка-вызов)
    # Строка справки-вызова о государственной аккредитации (кем выдана,
    # реквизиты); задаётся при внедрении по реестру Рособрнадзора
    ORG_ACCREDITATION = os.environ.get(
        "AIS_ACCREDITATION",
        "Федеральная служба по надзору в сфере образования и науки "
        "(реквизиты задаются в настройках АИС при внедрении)")
    BACKUP_DIR = os.path.join(INSTANCE_DIR, "backups")
    # Локальная языковая модель для разбора обращений (llama-server на
    # сервере вуза). Пустой адрес — функция выключена, регистрация вручную.
    LLM_URL = os.environ.get("AIS_LLM_URL", "")
    LLM_TIMEOUT = float(os.environ.get("AIS_LLM_TIMEOUT", "30"))
    LLM_MODEL = os.environ.get("AIS_LLM_MODEL", "local")


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "test"
    LLM_URL = ""
