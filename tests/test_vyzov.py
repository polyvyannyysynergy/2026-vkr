"""Справка-вызов по форме приказа Минобрнауки России от 19.12.2013 № 1368."""
import pytest
from conftest import NOW, login, new_request, type_id

from app.models import CertType, Request, Student, db
from app.services import WorkflowError, create_request

VYZOV = {"name_dat": "Тестовой Анне Ивановне", "basis": "PA",
         "period_from": "2027-01-12", "period_to": "2027-01-31"}


@pytest.fixture
def vyz(app):
    db.session.add(CertType(code="VYZ", name="Справка-вызов", lead_days=5,
                            max_copies=2, printable=True, electronic=False))
    db.session.commit()


def _vyz_in_work(client):
    login(client, "stud")
    new_request(client, code="VYZ", purpose="ООО «Ромашка»")
    rid = Request.query.one().id
    client.post("/logout")
    login(client, "oper")
    client.post(f"/staff/requests/{rid}", data={"to_status": "PREP"})
    return rid


def test_vyzov_is_not_issued_electronically(vyz):
    st = Student.query.first()
    with pytest.raises(WorkflowError):
        create_request(st, type_id("VYZ"), "ООО «Ромашка»", 1, "EL",
                       author=st.user, now=NOW)


def test_vyzov_cannot_be_ready_without_period_and_basis(client, vyz):
    rid = _vyz_in_work(client)
    page = client.post(f"/staff/requests/{rid}", data={"to_status": "READY"},
                       follow_redirects=True).get_data(as_text=True)
    assert "данные справки-вызова" in page
    assert db.session.get(Request, rid).status.code == "PREP"


def test_vyzov_period_end_before_start_is_refused(client, vyz):
    rid = _vyz_in_work(client)
    bad = dict(VYZOV, period_from="2027-01-31", period_to="2027-01-12")
    client.post(f"/staff/requests/{rid}/vyzov", data=bad)
    req = db.session.get(Request, rid)
    assert req.period_from is None and req.period_to is None


def test_vyzov_print_follows_form_1368(client, vyz):
    rid = _vyz_in_work(client)
    r = client.post(f"/staff/requests/{rid}/vyzov", data=VYZOV)
    assert r.status_code == 302
    r = client.post(f"/staff/requests/{rid}", data={"to_status": "READY"})
    assert db.session.get(Request, rid).status.code == "READY"
    page = client.get(f"/staff/requests/{rid}/print").get_data(as_text=True)
    for text in ("СПРАВКА-ВЫЗОВ", "Работодателю ООО «Ромашка»",
                 "статьей 173 Трудового кодекса", "Тестовой Анне Ивановне",
                 "по очной форме обучения на 2 курсе",
                 "прохождения промежуточной аттестации",
                 "с 12.01.2027 по 31.01.2027",
                 "продолжительностью 20 календарных дней",
                 "линия отрыва",
                 "Тестова Анна Ивановна находилась в Университете"):
        assert text in page, text
    pdf = client.get(f"/staff/requests/{rid}/pdf")
    assert pdf.mimetype == "application/pdf" and pdf.data[:4] == b"%PDF"


@pytest.mark.parametrize("nom, dat", [
    ("Тестова Анна Ивановна", "Тестовой Анне Ивановне"),
    ("Иванова Мария Сергеевна", "Ивановой Марии Сергеевне"),
    ("Семёнова Ксения Артёмовна", "Семёновой Ксении Артёмовне"),
    ("Петров Иван Сергеевич", "Петрову Ивану Сергеевичу"),
    ("Яковлев Матвей Ильич", "Яковлеву Матвею Ильичу"),
    ("Павлов Павел Олегович", "Павлову Павлу Олеговичу"),
    ("Никитин Илья Андреевич", "Никитину Илье Андреевичу"),
    ("Вишневская Дарья Олеговна", "Вишневской Дарье Олеговне"),
])
def test_dative_hint_for_vyzov(nom, dat):
    from app.services import dative_name
    assert dative_name(nom) == dat
