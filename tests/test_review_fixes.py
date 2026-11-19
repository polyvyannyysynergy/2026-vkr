"""Исправления по ревью кода 18.11.2026: граничные случаи, которые раньше давали
ошибку 500 или небезопасное поведение."""
import os
import socket
import threading

import pytest
from conftest import login, new_request, type_id
from test_vyzov import VYZOV, _vyz_in_work, vyz  # noqa: F401  (фикстура)

from app import instance_secret, llm, services
from app.models import Request, Student, TypeCheck, db
from app.reports import csv_cell
from app.type_check import run_type_checks
from app.views.auth import safe_next


# --- справка-вызов без сведений не печатается (было: 500) --------------------

def test_vyzov_without_details_is_not_printed(client, vyz):  # noqa: F811
    rid = _vyz_in_work(client)
    page = client.get(f"/staff/requests/{rid}").get_data(as_text=True)
    assert "Печатная форма справки" not in page
    assert "после заполнения её сведений" in page
    assert client.get(f"/staff/requests/{rid}/print").status_code == 403
    assert client.get(f"/staff/requests/{rid}/pdf").status_code == 403
    client.post(f"/staff/requests/{rid}/vyzov", data=VYZOV)
    assert client.get(f"/staff/requests/{rid}/print").status_code == 200


# --- перенаправление после входа — только на свой сайт ------------------------

@pytest.mark.parametrize("nxt", ["//evil.example", "/\t/evil.example", "/\\evil.example",
                                 "https://evil.example/", "/\n/evil.example", "evil", ""])
def test_safe_next_rejects_foreign(nxt):
    assert safe_next(nxt) is None


@pytest.mark.parametrize("nxt", ["/staff/", "/student/requests?status=NEW"])
def test_safe_next_keeps_local(nxt):
    assert safe_next(nxt) == nxt


def test_login_tab_redirect_goes_home(client):
    r = client.post("/login", query_string={"next": "/\t/evil.example"},
                    data={"login": "stud", "password": "pass12345"})
    assert r.status_code == 302 and "evil" not in r.headers["Location"]


# --- ключ сессии не из исходников ---------------------------------------------

def test_instance_secret_created_once(tmp_path):
    key = instance_secret(str(tmp_path))
    assert len(key) == 64 and instance_secret(str(tmp_path)) == key
    assert oct(os.stat(tmp_path / "secret.key").st_mode & 0o777) == "0o600"


# --- номер заявки, занятый параллельной подачей -------------------------------

def test_submit_request_retries_taken_number(client, monkeypatch):
    login(client, "stud")
    new_request(client)
    taken = Request.query.one().number
    real, calls = services.next_number, []

    def first_taken(year):  # первая попытка — номер, который уже занят
        calls.append(year)
        return taken if len(calls) == 1 else real(year)
    monkeypatch.setattr(services, "next_number", first_taken)
    r = new_request(client)
    assert r.status_code == 302 and len(calls) == 2
    assert Request.query.count() == 2


# --- повтор номера зачётной книжки (было: 500) ---------------------------------

def test_duplicate_record_book_is_refused(client):
    login(client, "adm")
    data = dict(login="newstud", full_name="Новый Студент Иванович", role="STUDENT",
                password="pass12345", record_book_no="STUD", birth_date="2005-01-01",
                faculty="ФИТ", direction="09.03.02", group_code="ИСТ-231", course=1,
                study_form="OCH", funding="BUD", enroll_order="1-с",
                enroll_date="2023-09-01", graduation_date="2027-06-30")
    r = client.post("/admin/users/new", data=data, follow_redirects=True)
    assert r.status_code == 200
    assert "уже есть" in r.get_data(as_text=True)
    assert Student.query.filter_by(record_book_no="STUD").count() == 1


# --- род по отчеству «… кызы» --------------------------------------------------

@pytest.mark.parametrize("name, female", [
    ("Алиева Лейла Рашид кызы", True), ("Алиева Лейла Рашидкызы", True),
    ("Мамедова Айнур Ильхам гызы", True), ("Тестова Анна Ивановна", True),
    ("Петров Пётр Петрович", False), ("Ли Вэй", False)])
def test_is_female(name, female):
    assert services.is_female(name) is female


# --- CSV: ячейка не исполняется как формула -----------------------------------

@pytest.mark.parametrize("value, out", [("=1+2", "'=1+2"), ("+7 900", "'+7 900"),
                                        ("@SUM(A1)", "'@SUM(A1)"), ("-1", "'-1"),
                                        ("ИСТ-231", "ИСТ-231"), (2, 2)])
def test_csv_cell(value, out):
    assert csv_cell(value) == out


def test_registry_csv_neutralises_formula(client):
    login(client, "oper")
    client.post("/staff/requests/new", data={
        "cert_type": type_id("OB"), "purpose": "по месту требования", "copies": 1,
        "delivery": "DEAN", "record_book_no": "STUD", "channel": "ELK",
        "ext_number": "=1+2"})
    body = client.get("/staff/export.csv").get_data().decode("utf-8-sig")
    assert ";'=1+2;" in body and ";=1+2;" not in body


# --- ответ не по HTTP — «модель недоступна», а не 500 ---------------------------

def test_garbage_http_answer_is_unavailable():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)

    def serve():
        c, _ = s.accept()
        c.recv(65536)
        c.sendall(b"GARBAGE\r\n\r\n")
        c.close()
    threading.Thread(target=serve, daemon=True).start()
    with pytest.raises(llm.LlmUnavailable):
        llm.parse_appeal("Прошу справку об обучении", [("OB", "Справка об обучении")],
                         f"http://127.0.0.1:{s.getsockname()[1]}", timeout=3)
    s.close()


# --- непригодный ответ по одной заявке не останавливает проверку остальных ------

def test_bad_answer_does_not_block_other_checks(client, monkeypatch):
    login(client, "stud")
    new_request(client)
    new_request(client)
    first = min(r.id for r in Request.query.all())

    def fake(purpose, comment, spec, url, timeout, model):
        if fake.calls == 0:
            fake.calls += 1
            raise llm.LlmBadAnswer("bad answer")
        fake.calls += 1
        return {"suitable_codes": ["OB"]}
    fake.calls = 0
    monkeypatch.setattr(llm, "check_type", fake)
    assert run_type_checks("http://x", 1, "m") == (2, 0)
    tc = TypeCheck.query.filter_by(request_id=first).one()
    assert tc.suggested_type_id is None


def test_network_error_still_stops_checks(client, monkeypatch):
    login(client, "stud")
    new_request(client)

    def down(*args, **kwargs):
        raise llm.LlmUnavailable("URLError")
    monkeypatch.setattr(llm, "check_type", down)
    with pytest.raises(llm.LlmUnavailable):
        run_type_checks("http://x", 1, "m")
    assert TypeCheck.query.count() == 0


# --- вход под несуществующим логином: тот же ответ ----------------------------

def test_unknown_login_same_message(client):
    a = login(client, "nosuchuser", "x").get_data(as_text=True)
    b = login(client, "stud", "wrong-pass").get_data(as_text=True)
    assert "Неверный логин или пароль" in a and "Неверный логин или пароль" in b
    db.session.rollback()
