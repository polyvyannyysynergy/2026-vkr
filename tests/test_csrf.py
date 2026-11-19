"""CSRF-защита форм."""
import re

from app import create_app, init_classifiers
from app.config import TestConfig
from app.models import Role, User, db


class CsrfConfig(TestConfig):
    WTF_CSRF_ENABLED = True


def test_post_without_token_rejected_and_with_token_accepted():
    app = create_app(CsrfConfig)
    with app.app_context():
        init_classifiers()
        u = User(login="u1", full_name="U", role=Role.query.first())
        u.set_password("pass12345")
        db.session.add(u)
        db.session.commit()
        c = app.test_client()
        r = c.post("/login", data={"login": "u1", "password": "pass12345"})
        assert r.status_code == 400
        assert "CSRF" in r.get_data(as_text=True)
        page = c.get("/login").get_data(as_text=True)
        token = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"',
                          page).group(1)
        r = c.post("/login", data={"login": "u1", "password": "pass12345",
                                   "csrf_token": token})
        assert r.status_code == 302
