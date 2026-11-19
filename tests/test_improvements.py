"""Улучшения по ревью кода 18.11.2026 (вторая часть): перенос праздника с
выходного без ручного списка, одновременная обработка заявки двумя
сотрудниками, перенос длинного слова в печатной форме справки."""
from datetime import date, timedelta

import pytest
from conftest import login, new_request
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from sqlalchemy import text

from app import services
from app.certificate import _register_fonts, _wrap
from app.config import (FIXED_HOLIDAYS, TRANSFERRED_DAYS_OFF, Config,
                        weekend_holiday_transfers)
from app.models import Request, StatusHistory, User, db
from app.workdays import add_workdays

HOL = Config.HOLIDAYS


# --- ч. 2 ст. 112 ТК РФ: праздник в выходной -> выходной в следующий рабочий день

def test_weekend_holiday_moves_day_off_after_2027():
    # 04.11.2028 — суббота: понедельник 06.11.2028 нерабочий
    # (постановления о переносах на 2028 г. ещё нет)
    assert add_workdays(date(2028, 11, 3), 1, HOL) == date(2028, 11, 7)
    # 04.11.2029 — воскресенье: 05.11.2029 нерабочий
    assert add_workdays(date(2029, 11, 2), 1, HOL) == date(2029, 11, 6)


def test_auto_transfers_match_government_decrees():
    # переносы, которые даёт правило, есть в постановлениях № 1466 и № 1187;
    # январские праздники правило не переносит (их переносит Правительство)
    for year, decree in TRANSFERRED_DAYS_OFF.items():
        auto = weekend_holiday_transfers(year)
        assert auto <= {date.fromisoformat(d) for d in decree}
    assert weekend_holiday_transfers(2027) == {
        date(2027, 5, 3), date(2027, 5, 10), date(2027, 6, 14)}
    # 01.01.2028 и 08.01.2028 — субботы, но январские праздники не переносятся
    assert all(d.month != 1 for d in weekend_holiday_transfers(2028))
    assert (1, 1) in FIXED_HOLIDAYS


# --- два сотрудника обрабатывают одну заявку --------------------------------

def _one_request(client):
    login(client, "stud")
    new_request(client)
    client.post("/logout")
    return Request.query.one().id


def test_stale_page_does_not_override_other_staff(client):
    rid = _one_request(client)
    login(client, "oper")
    page = client.get(f"/staff/requests/{rid}").get_data(as_text=True)
    assert 'name="seen_status"' in page and 'value="NEW"' in page
    # пока страница открыта, другой сотрудник взял заявку в работу
    services.change_status(db.session.get(Request, rid), "PREP",
                           User.query.filter_by(login="adm").one())
    db.session.commit()
    r = client.post(f"/staff/requests/{rid}", follow_redirects=True, data={
        "to_status": "REJ", "comment": "не тот вид справки", "seen_status": "NEW"})
    assert "изменил другой сотрудник" in r.get_data(as_text=True)
    assert db.session.get(Request, rid).status.code == "PREP"


def test_simultaneous_change_second_is_refused(client):
    rid = _one_request(client)
    req = db.session.get(Request, rid)
    assert req.status.code == "NEW"          # заявка прочитана первым запросом
    # второй запрос успел перевести её в «Готовится»
    db.session.execute(text(
        "UPDATE requests SET status_id = (SELECT id FROM statuses WHERE code='PREP') "
        "WHERE id = :i"), {"i": rid})
    history = StatusHistory.query.count()
    with pytest.raises(services.WorkflowError, match="одновременно"):
        services.change_status(req, "PREP", User.query.filter_by(login="oper").one())
    db.session.rollback()
    assert StatusHistory.query.count() == history


# --- просрочка: со дня после плановой даты и только у заявки в работе ---------

def test_overdue_mark_starts_day_after_planned_date(client):
    rid = _one_request(client)
    login(client, "oper")
    req = db.session.get(Request, rid)
    oper = User.query.filter_by(login="oper").one()
    for planned, late in ((date.today() - timedelta(days=1), True), (date.today(), False)):
        req.planned_date = planned
        db.session.commit()
        card = client.get(f"/staff/requests/{rid}").get_data(as_text=True)
        registry = client.get("/staff/").get_data(as_text=True)
        assert ("просрочена" in card) is late
        assert ('class="overdue"' in registry) is late
    req.planned_date = date.today() - timedelta(days=1)
    services.change_status(req, "PREP", oper)
    services.change_status(req, "READY", oper)
    db.session.commit()
    assert "просрочена" not in client.get(f"/staff/requests/{rid}").get_data(as_text=True)


# --- печатная форма: слово шире строки ---------------------------------------

@pytest.mark.parametrize("par", [
    "Справка выдана для предъявления https://example.org/" + "a" * 160 + " по месту требования",
    "x" * 300,
    "Обычный текст справки без длинных слов",
])
def test_wrap_keeps_every_line_inside_field(app, par):
    _register_fonts()
    width = 100 * mm
    lines = _wrap(par, "AisSerif", 12, width)
    assert lines and "" not in lines
    assert all(stringWidth(line, "AisSerif", 12) <= width for line in lines)
    assert "".join(lines).replace(" ", "") == par.replace(" ", "")
