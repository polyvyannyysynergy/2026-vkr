"""Создание заявок, нумерация, переходы статусов."""
from datetime import date

import pytest
from conftest import NOW, login, new_request

from app.models import Request, Student, User, db
from app.services import WorkflowError, change_status, create_request


def test_student_creates_request(client):
    login(client, "stud")
    r = new_request(client, copies=2, delivery="EL")
    assert r.status_code == 302
    req = Request.query.one()
    assert req.status.code == "NEW"
    assert req.number == f"{date.today().year}-00001"
    assert req.copies == 2 and req.delivery == "EL"
    assert len(req.history) == 1
    page = client.get(r.headers["Location"]).get_data(as_text=True)
    assert req.number in page and "Новая" in page


def test_numbering_sequential_within_year(app):
    st = Student.query.first()
    nums = [create_request(st, 1, "цель", 1, "DEAN", author=st.user,
                           now=NOW).number for _ in range(3)]
    assert nums == ["2026-00001", "2026-00002", "2026-00003"]
    assert Request.query.filter_by(number="2026-00002").one().planned_date \
        == date(2026, 11, 5)  # пн 02.11 + 2 раб. дня, 04.11 праздник


def test_validation_rules(app):
    st = Student.query.first()
    with pytest.raises(WorkflowError):   # почта без адреса
        create_request(st, 1, "цель", 1, "POST", author=st.user)
    with pytest.raises(WorkflowError):   # превышение экземпляров
        create_request(st, 1, "цель", 9, "DEAN", author=st.user)
    with pytest.raises(WorkflowError):   # бланк нельзя электронно
        create_request(st, 2, "цель", 1, "EL", author=st.user)
    with pytest.raises(WorkflowError):   # неактивный тип
        create_request(st, 3, "цель", 1, "DEAN", author=st.user)


def test_full_workflow_by_operator(client, app):
    login(client, "stud")
    new_request(client)
    rid = Request.query.one().id
    client.post("/logout")
    login(client, "oper")
    for code in ("PREP", "READY", "ISSUED"):
        r = client.post(f"/staff/requests/{rid}",
                        data={"to_status": code, "comment": "ok"})
        assert r.status_code == 302, code
    req = db.session.get(Request, rid)
    db.session.refresh(req)
    assert req.status.code == "ISSUED"
    assert req.operator.login == "oper" and req.ready_at and req.closed_at
    assert [h.to_status.code for h in req.history] == [
        "NEW", "PREP", "READY", "ISSUED"]


def test_forbidden_transitions(app):
    st = Student.query.first()
    oper = User.query.filter_by(login="oper").one()
    req = create_request(st, 1, "цель", 1, "DEAN", author=st.user)
    with pytest.raises(WorkflowError):
        change_status(req, "ISSUED", oper)        # NEW -> ISSUED нельзя
    with pytest.raises(WorkflowError):
        change_status(req, "PREP", st.user)       # студенту нельзя в работу
    with pytest.raises(WorkflowError):
        change_status(req, "REJ", oper, "")       # отказ без причины
    change_status(req, "REJ", oper, "Нет оснований для выдачи")
    with pytest.raises(WorkflowError):
        change_status(req, "PREP", oper)          # из финального статуса


def test_student_cancels_only_new(client):
    login(client, "stud")
    new_request(client)
    req = Request.query.one()
    client.post(f"/student/requests/{req.id}/cancel")
    db.session.refresh(req)
    assert req.status.code == "CANC"
    client.post(f"/student/requests/{req.id}/cancel")  # повторно — отказ
    db.session.refresh(req)
    assert len(req.history) == 2


def test_rejection_reason_visible_to_student(client):
    login(client, "stud")
    new_request(client)
    rid = Request.query.one().id
    client.post("/logout")
    login(client, "oper")
    client.post(f"/staff/requests/{rid}", data={
        "to_status": "REJ", "comment": "Не указано место предоставления"})
    client.post("/logout")
    login(client, "stud")
    page = client.get(f"/student/requests/{rid}").get_data(as_text=True)
    assert "Отклонена" in page and "Не указано место предоставления" in page
