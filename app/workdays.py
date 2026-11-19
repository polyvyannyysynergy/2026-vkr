"""Расчётный модуль: плановая дата готовности справки по рабочим дням.

Отсчёт ведётся со дня, следующего за днём подачи заявки. Субботы,
воскресенья и праздничные дни из конфигурации не считаются. Заявка,
поданная после окончания рабочего дня (CUTOFF_HOUR), считается
поданной на следующий день.
"""
from datetime import datetime, timedelta

from .config import WORKING_WEEKENDS

CUTOFF_HOUR = 17  # час, после которого заявка относится к следующему дню


def is_workday(day, holidays=frozenset()):
    """Рабочий ли день: пн–пт и не праздник либо выходной, объявленный рабочим."""
    if day in WORKING_WEEKENDS:
        return True
    return day.weekday() < 5 and day not in holidays


def add_workdays(start, n, holidays=frozenset()):
    """Дата, отстоящая от start на n рабочих дней вперёд.

    При n == 0 возвращается ближайший рабочий день, не ранее start.
    """
    if n < 0:
        raise ValueError("Срок изготовления не может быть отрицательным")
    day = start
    if n == 0:
        while not is_workday(day, holidays):
            day += timedelta(days=1)
        return day
    left = n
    while left > 0:
        day += timedelta(days=1)
        if is_workday(day, holidays):
            left -= 1
    return day


def planned_date(created_at, lead_days, holidays=frozenset()):
    """Плановая дата готовности для заявки, созданной в момент created_at."""
    if isinstance(created_at, datetime):
        base = created_at.date()
        if created_at.hour >= CUTOFF_HOUR:
            base += timedelta(days=1)
    else:
        base = created_at
    # заявка, поданная в выходной, принимается в первый рабочий день
    base = add_workdays(base, 0, holidays)
    return add_workdays(base, lead_days, holidays)


def workdays_between(start, end, holidays=frozenset()):
    """Число рабочих дней в полуинтервале (start, end]."""
    if isinstance(start, datetime):
        start = start.date()
    if isinstance(end, datetime):
        end = end.date()
    sign = 1
    if end < start:
        start, end, sign = end, start, -1
    count, day = 0, start
    while day < end:
        day += timedelta(days=1)
        if is_workday(day, holidays):
            count += 1
    return sign * count
