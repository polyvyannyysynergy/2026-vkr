"""Единый реестр: заявки из любых каналов (АИС, ЕЛК, МФСО, куратор)."""
import pytest
from conftest import NOW, login, new_request, type_id

from app.models import Request, Student
from app.reports import statistics
from app.services import WorkflowError, create_request


def staff_register(client, **extra):
    data = {"record_book_no": "STUD", "cert_type": type_id("OB"),
            "channel": "ELK", "ext_number": "ЕЛК-000123",
            "purpose": "по месту работы", "copies": 1, "delivery": "DEAN"}
    data.update(extra)
    return client.post("/staff/requests/new", data=data)


def test_student_request_is_registered_with_ais_channel(client):
    login(client, "stud")
    new_request(client)
    req = Request.query.one()
    assert req.channel == "AIS" and req.ext_number is None


def test_staff_registers_request_from_elk_with_external_number(client):
    login(client, "oper")
    r = staff_register(client)
    assert r.status_code == 302
    req = Request.query.one()
    assert req.channel == "ELK" and req.ext_number == "ЕЛК-000123"
    assert req.student.record_book_no == "STUD"
    assert req.status.code == "NEW"
    first = req.history[0]
    assert first.author.login == "oper" and "ЕЛК" in first.comment


def test_staff_registration_unknown_record_book_is_refused(client):
    login(client, "oper")
    r = staff_register(client, record_book_no="NOPE")
    assert r.status_code == 200
    assert "не найден" in r.get_data(as_text=True)
    assert Request.query.count() == 0


def test_student_cannot_open_staff_registration(client):
    login(client, "stud")
    assert client.get("/staff/requests/new").status_code == 403
    assert staff_register(client).status_code == 403
    assert Request.query.count() == 0


def test_service_rejects_unknown_channel_and_student_external_channel(app):
    st = Student.query.first()
    with pytest.raises(WorkflowError):   # неизвестный канал
        create_request(st, type_id("OB"), "цель", 1, "DEAN", author=st.user,
                       channel="FAX", now=NOW)
    with pytest.raises(WorkflowError):   # студент не регистрирует «чужой» канал
        create_request(st, type_id("OB"), "цель", 1, "DEAN", author=st.user,
                       channel="ELK", now=NOW)


def test_registry_filters_and_shows_channel(client):
    login(client, "stud")
    new_request(client)
    client.post("/logout")
    login(client, "oper")
    staff_register(client, channel="MFSO", ext_number="")
    page = client.get("/staff/?channel=MFSO").get_data(as_text=True)
    assert "Найдено заявок: 1" in page and "МФСО" in page
    page = client.get("/staff/?channel=AIS").get_data(as_text=True)
    assert "Найдено заявок: 1" in page


def test_registry_csv_contains_channel(client):
    login(client, "oper")
    staff_register(client)
    text = client.get("/staff/export.csv").data.decode("utf-8-sig")
    header, row = text.strip().split("\r\n")
    assert "Канал" in header.split(";")
    assert "ЕЛК" in row.split(";")


def test_report_counts_requests_by_channel(client, app):
    login(client, "stud")
    new_request(client)
    client.post("/logout")
    login(client, "oper")
    staff_register(client)
    staff_register(client, channel="KUR", ext_number="")
    s = statistics()
    assert {k: v["total"] for k, v in s["by_channel"].items()} == {
        "AIS": 1, "ELK": 1, "MFSO": 0, "KUR": 1}
    page = client.get("/staff/reports").get_data(as_text=True)
    assert "По каналам поступления" in page and "Куратор" in page
