"""Аутентификация, блокировка, выход."""
from conftest import login

from app.models import AuditLog, User


def test_login_success_redirects_by_role(client):
    r = login(client, "stud")
    assert r.status_code == 302
    assert client.get("/").headers["Location"].endswith("/student/")
    client.post("/logout")
    login(client, "oper")
    assert client.get("/").headers["Location"].endswith("/staff/")


def test_login_wrong_password(client, app):
    r = login(client, "stud", "wrong")
    assert r.status_code == 200
    assert "Неверный логин или пароль" in r.get_data(as_text=True)
    with app.app_context():
        assert AuditLog.query.filter_by(action="LOGIN_FAIL").count() == 1


def test_password_is_hashed(app):
    u = User.query.filter_by(login="stud").one()
    assert u.password_hash != "pass12345"
    assert u.password_hash.startswith(("scrypt:", "pbkdf2:"))
    assert u.check_password("pass12345")


def test_lockout_after_failed_attempts(client, app):
    for _ in range(app.config["MAX_FAILED_LOGINS"]):
        login(client, "stud", "bad")
    r = login(client, "stud")  # верный пароль, но учётка заблокирована
    assert "временно заблокирована" in r.get_data(as_text=True)


def test_anonymous_redirected_to_login(client):
    r = client.get("/staff/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_logout_requires_post_and_clears_session(client):
    login(client, "stud")
    assert client.get("/logout").status_code == 405
    client.post("/logout")
    assert client.get("/student/").status_code == 302


def test_open_redirect_blocked(client):
    r = client.post("/login?next=//evil.example", data={
        "login": "stud", "password": "pass12345"})
    assert "evil" not in r.headers["Location"]
