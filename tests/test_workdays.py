"""Расчётный модуль: плановая дата по рабочим дням."""
from datetime import date, datetime

import pytest

from app.config import Config
from app.workdays import add_workdays, planned_date, workdays_between

HOL = Config.HOLIDAYS


def test_add_workdays_skips_weekend():
    # пятница 06.11.2026 + 1 рабочий день = понедельник 09.11.2026
    assert add_workdays(date(2026, 11, 6), 1) == date(2026, 11, 9)


def test_add_workdays_skips_holiday():
    # 03.11.2026 (вт) + 1 раб. день: 04.11 — праздник, результат 05.11
    assert add_workdays(date(2026, 11, 3), 1, HOL) == date(2026, 11, 5)


def test_zero_days_moves_to_next_workday():
    assert add_workdays(date(2026, 11, 7), 0) == date(2026, 11, 9)
    assert add_workdays(date(2026, 11, 5), 0) == date(2026, 11, 5)


def test_planned_date_cutoff_and_weekend():
    # подана в пятницу 06.11 в 10:00, 2 раб. дня -> вт 10.11
    assert planned_date(datetime(2026, 11, 6, 10), 2, HOL) == date(2026, 11, 10)
    # подана в пятницу 06.11 в 18:00 -> считается с пн 09.11 -> ср 11.11
    assert planned_date(datetime(2026, 11, 6, 18), 2, HOL) == date(2026, 11, 11)
    # подана в праздник 04.11 -> принята 05.11 -> 2 раб. дня -> 09.11
    assert planned_date(datetime(2026, 11, 4, 11), 2, HOL) == date(2026, 11, 9)


def test_new_year_holidays_with_transfer():
    # 30.12.2026 (ср) + 3 раб. дня: 31.12.2026 — перенесённый выходной
    # (ПП РФ № 1466), 01–08.01 праздники, 09–10.01 выходные ->
    # 11.01 (1), 12.01 (2), 13.01.2027 (3)
    assert add_workdays(date(2026, 12, 30), 3, HOL) == date(2027, 1, 13)
    # 09.01.2026 — перенесённый выходной: 08.01.2026 + 1 = пн 12.01.2026
    assert add_workdays(date(2026, 1, 8), 1, HOL) == date(2026, 1, 12)
    # праздники ст. 112 ТК РФ есть и после 2027 г. (до 15.11.2026 — только 2026–2027):
    # 30.12.2027 + 1: 31.12.2027 — перенос, 01–08.01.2028 — праздники, 09.01 — вс -> 10.01.2028
    assert add_workdays(date(2027, 12, 30), 1, HOL) == date(2028, 1, 10)
    # 12.06.2035 (вт) — День России
    assert add_workdays(date(2035, 6, 11), 1, HOL) == date(2035, 6, 13)


def test_transfers_2027_and_working_saturday():
    # 20.02.2027 (сб) — рабочий день, 22–23.02.2027 — нерабочие
    assert add_workdays(date(2027, 2, 19), 1, HOL) == date(2027, 2, 20)
    assert add_workdays(date(2027, 2, 20), 1, HOL) == date(2027, 2, 24)
    # 09.05.2026 (сб) праздник -> 11.05.2026 (пн) выходной
    assert add_workdays(date(2026, 5, 8), 1, HOL) == date(2026, 5, 12)


def test_workdays_between_and_negative():
    assert workdays_between(date(2026, 11, 2), date(2026, 11, 9), HOL) == 4
    assert workdays_between(date(2026, 11, 9), date(2026, 11, 2), HOL) == -4
    with pytest.raises(ValueError):
        add_workdays(date(2026, 11, 2), -1)
