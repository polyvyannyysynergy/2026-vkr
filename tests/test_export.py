"""Отчёт, экспорт CSV, печатная форма и PDF справки."""
from conftest import login, new_request

from app.models import Request, db


def _ready_request(client):
    login(client, "stud")
    new_request(client, delivery="EL")
    rid = Request.query.one().id
    client.post("/logout")
    login(client, "oper")
    client.post(f"/staff/requests/{rid}", data={"to_status": "PREP"})
    client.post(f"/staff/requests/{rid}", data={"to_status": "READY"})
    return rid


def test_registry_csv_export(client):
    rid = _ready_request(client)
    r = client.get("/staff/export.csv?status=READY")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    text = r.data.decode("utf-8-sig")
    lines = text.strip().split("\r\n")
    assert lines[0].startswith("Номер;Дата подачи;Студент")
    assert len(lines) == 2 and db.session.get(Request, rid).number in lines[1]
    empty = client.get("/staff/export.csv?status=NEW").data.decode("utf-8-sig")
    assert len(empty.strip().split("\r\n")) == 1


def test_registry_filters(client):
    _ready_request(client)
    page = client.get("/staff/?q=Тестова").get_data(as_text=True)
    assert "Найдено заявок: 1" in page
    page = client.get("/staff/?q=Несуществующий").get_data(as_text=True)
    assert "Найдено заявок: 0" in page


def test_report_and_report_csv(client):
    _ready_request(client)
    page = client.get("/staff/reports").get_data(as_text=True)
    assert "Статистика обработки заявок" in page
    r = client.get("/staff/reports.csv")
    rows = r.data.decode("utf-8-sig").strip().split("\r\n")
    assert rows[-1].startswith("ИТОГО;1;1;")


def test_certificate_print_and_pdf(client):
    rid = _ready_request(client)
    page = client.get(f"/staff/requests/{rid}/print").get_data(as_text=True)
    assert "СПРАВКА ОБ ОБУЧЕНИИ" in page and "Тестова Анна Ивановна" in page
    assert "он(а)" not in page and "Зачислен(а)" not in page  # без указания рода
    r = client.get(f"/staff/requests/{rid}/pdf")
    assert r.mimetype == "application/pdf" and r.data.startswith(b"%PDF")
    client.post("/logout")
    login(client, "stud")
    r = client.get(f"/student/requests/{rid}/pdf")
    assert r.status_code == 200 and r.data.startswith(b"%PDF")


def test_staff_cannot_print_new_request(client):
    login(client, "stud")
    new_request(client)
    rid = Request.query.one().id
    client.post("/logout")
    login(client, "oper")
    assert client.get(f"/staff/requests/{rid}/print").status_code == 403
    assert client.get(f"/staff/requests/{rid}/pdf").status_code == 403
