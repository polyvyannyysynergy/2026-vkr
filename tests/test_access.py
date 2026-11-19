"""Разграничение доступа по ролям."""
from conftest import login, new_request

from app.models import Request


def test_student_cannot_open_staff_and_admin(client):
    login(client, "stud")
    assert client.get("/staff/").status_code == 403
    assert client.get("/admin/types").status_code == 403
    assert client.get("/staff/export.csv").status_code == 403


def test_staff_cannot_open_admin(client):
    login(client, "oper")
    assert client.get("/staff/").status_code == 200
    assert client.get("/admin/users").status_code == 403


def test_admin_has_all_management_sections(client):
    login(client, "adm")
    for url in ("/staff/", "/staff/reports", "/admin/types", "/admin/users",
                "/admin/audit"):
        assert client.get(url).status_code == 200, url


def test_student_cannot_see_foreign_request(client, app):
    login(client, "stud2")
    new_request(client)
    rid = Request.query.one().id
    client.post("/logout")
    login(client, "stud")
    assert client.get(f"/student/requests/{rid}").status_code == 404


def test_security_headers(client):
    r = client.get("/login")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
