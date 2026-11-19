import json
import os
import sys
import threading
import time
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, init_classifiers  # noqa: E402
from app.config import TestConfig  # noqa: E402
from app.models import CertType, Role, Student, User, db  # noqa: E402


def make_user(login, role_code, name):
    u = User(login=login, full_name=name,
             role=Role.query.filter_by(code=role_code).one())
    u.set_password("pass12345")
    db.session.add(u)
    return u


def make_student(login, name, form="OCH"):
    u = make_user(login, "STUDENT", name)
    st = Student(user=u, record_book_no=login.upper(), birth_date=date(2005, 3, 1),
                 faculty="ФИТ", direction="09.03.02 ИСиТ", group_code="ИСТ-231",
                 course=2, study_form=form, funding="BUD", enroll_order="1-с",
                 enroll_date=date(2023, 8, 30), graduation_date=date(2027, 6, 30))
    db.session.add(st)
    return st


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        init_classifiers()
        db.session.add_all([
            CertType(code="OB", name="Справка об обучении", lead_days=2,
                     max_copies=3, printable=True),
            CertType(code="AKD", name="Академическая справка", lead_days=10,
                     max_copies=1, printable=False),
            CertType(code="OLD", name="Архивная", lead_days=5, is_active=False),
        ])
        make_student("stud", "Тестова Анна Ивановна")
        make_student("stud2", "Другой Пётр Петрович")
        make_user("oper", "STAFF", "Операторова Ольга")
        make_user("adm", "ADMIN", "Админов Антон")
        db.session.commit()
        yield app


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, user, password="pass12345"):
    return client.post("/login", data={"login": user, "password": password},
                       follow_redirects=False)


def type_id(code):
    return CertType.query.filter_by(code=code).one().id


def new_request(client, code="OB", **extra):
    data = {"cert_type": type_id(code), "purpose": "по месту требования",
            "copies": 1, "delivery": "DEAN"}
    data.update(extra)
    return client.post("/student/new", data=data)


NOW = datetime(2026, 11, 2, 10, 0)


# --- фейковый llama-server (тесты локальной ИИ) ----------------------------

def _serve(handler_cls):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


@pytest.fixture
def fake_llm():
    """Локальный фейковый llama-server на свободном порту (свой на тест)."""
    state = {"status": 200, "content": "{}", "delay": 0, "seen": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            state["seen"].append((self.path, json.loads(body)))
            time.sleep(state["delay"])
            out = json.dumps({"choices": [{"message": {
                "role": "assistant", "content": state["content"]}}]})
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out.encode())

        def log_message(self, *args):  # не печатать запросы в вывод тестов
            pass

    srv, url = _serve(Handler)
    state["url"] = url
    yield state
    srv.shutdown()
    srv.server_close()
