"""Blueprint staff: реестр заявок, обработка, печать справки, отчёты."""
import time
from datetime import date

from flask import (Blueprint, Response, abort, current_app, flash, g,
                   redirect, render_template, request, url_for)

from .. import llm
from ..certificate import certificate_pdf, certificate_text
from ..forms import AppealForm, RegisterForm, StatusForm, VyzovForm
from ..models import (ROLE_ADMIN, ROLE_STAFF, CertType, Request, Status,
                      Student, User, db)
from ..reports import (REGISTRY_HEADER, parse_date, registry_query,
                       registry_rows, statistics, to_csv)
from ..security import audit, role_required
from ..services import (OPEN_STATUSES, WorkflowError, allowed_targets,
                        change_status, dative_name, save_vyzov,
                        submit_request)

bp = Blueprint("staff", __name__, url_prefix="/staff")
STAFF_ROLES = (ROLE_STAFF, ROLE_ADMIN)


def get_request(req_id):
    req = db.session.get(Request, req_id)
    if req is None:
        abort(404)
    return req


@bp.route("/")
@role_required(*STAFF_ROLES)
def registry():
    page = request.args.get("page", 1, type=int)
    pager = registry_query(request.args).paginate(
        page=page, per_page=current_app.config["PAGE_SIZE"], error_out=False)
    groups = [g_[0] for g_ in db.session.query(Student.group_code)
              .distinct().order_by(Student.group_code)]
    args = {k: v for k, v in request.args.items() if k != "page"}
    return render_template(
        "staff/registry.html", pager=pager, args=args, groups=groups,
        statuses=Status.query.order_by(Status.sort_order).all(),
        types=CertType.query.order_by(CertType.sort_order).all(),
        open_codes=OPEN_STATUSES)


@bp.route("/requests/<int:req_id>", methods=["GET", "POST"])
@role_required(*STAFF_ROLES)
def process(req_id):
    req = get_request(req_id)
    targets = allowed_targets(req, g.user.role_code)
    names = {s.code: s.name for s in Status.query.all()}
    form = StatusForm()
    form.to_status.choices = [(c, names[c]) for c in targets]
    if targets and form.validate_on_submit():
        try:
            change_status(req, form.to_status.data, g.user, form.comment.data,
                          expected=form.seen_status.data)
            db.session.commit()
            flash(f"Заявка № {req.number}: статус «{req.status.name}»",
                  "success")
            return redirect(url_for("staff.process", req_id=req.id))
        except WorkflowError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    form.seen_status.data = req.status.code
    vform = None
    if req.is_vyzov and req.status.code in OPEN_STATUSES:
        vform = VyzovForm(obj=req, formdata=None)
        vform.name_dat.data = req.name_dat or _dative_hint(req)
    return render_template("staff/process.html", req=req, form=form,
                           targets=targets, open_codes=OPEN_STATUSES,
                           vform=vform)


def _dative_hint(req):
    """Подсказка для поля «ФИО в дательном падеже» — сотрудник проверяет."""
    return dative_name(req.student.user.full_name)


def _active_types():
    return (CertType.query.filter_by(is_active=True)
            .order_by(CertType.sort_order).all())


def _register_page(form, appeal=None, suggestion=None):
    """Страница регистрации; блок разбора обращения — если задан AIS_LLM_URL."""
    if appeal is None and current_app.config["LLM_URL"]:
        appeal = AppealForm(formdata=None)
    return render_template("staff/register.html", form=form, appeal=appeal,
                           suggestion=suggestion)


def _apply_suggestion(form, s):
    """Подставить предложения модели в форму; студента искать по БД."""
    filled = []
    for key in ("cert_type", "purpose", "copies", "delivery", "post_address",
                "record_book_no"):
        if key in s:
            getattr(form, key).data = s[key]
            filled.append(getattr(form, key).label.text)
    student = None
    if "record_book_no" in s:
        st = Student.query.filter_by(record_book_no=s["record_book_no"]).first()
        student = (f"Студент по № зачётки: {st.user.full_name}." if st else
                   "Студент с таким № зачётки не найден — проверьте номер.")
    elif "full_name" in s:
        found = (Student.query.join(User)
                 .filter(User.full_name == s["full_name"]).limit(2).all())
        if len(found) == 1:
            form.record_book_no.data = found[0].record_book_no
            filled.append(form.record_book_no.label.text)
            student = (f"№ зачётки подставлен по ФИО из базы: "
                       f"{s['full_name']}.")
        else:
            student = (f"По ФИО «{s['full_name']}» студент "
                       f"{'не найден' if not found else 'не однозначен'}"
                       " — укажите № зачётки.")
    return {"filled": filled, "student": student}


@bp.route("/requests/new", methods=["GET", "POST"])
@role_required(*STAFF_ROLES)
def register():
    """Регистрация заявки, принятой через ЕЛК, МФСО или от куратора."""
    form = RegisterForm()
    form.cert_type.choices = [(t.id, t.name) for t in _active_types()]
    if form.validate_on_submit():
        st = Student.query.filter_by(
            record_book_no=form.record_book_no.data.strip()).first()
        if st is None:
            flash("Студент с таким номером зачётной книжки не найден",
                  "danger")
        else:
            try:
                req = submit_request(
                    st, form.cert_type.data, form.purpose.data,
                    form.copies.data, form.delivery.data,
                    form.post_address.data, form.comment.data, author=g.user,
                    channel=form.channel.data, ext_number=form.ext_number.data)
                flash(f"Заявка № {req.number} зарегистрирована "
                      f"(канал: {req.channel_name})", "success")
                return redirect(url_for("staff.process", req_id=req.id))
            except WorkflowError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
    return _register_page(form)


@bp.route("/requests/new/parse", methods=["POST"])
@role_required(*STAFF_ROLES)
def parse_appeal():
    """Разбор текста обращения локальной моделью: только заполняет форму.

    Заявку создаёт сотрудник кнопкой «Зарегистрировать» после проверки;
    текст обращения не сохраняется, в журнал — только факт и исход.
    """
    cfg = current_app.config
    if not cfg["LLM_URL"]:
        abort(404)
    appeal = AppealForm()
    types = _active_types()
    form = RegisterForm(formdata=None)
    form.cert_type.choices = [(t.id, t.name) for t in types]
    suggestion = None
    if appeal.validate_on_submit():
        started = time.monotonic()
        try:
            raw = llm.parse_appeal(
                appeal.text.data,
                [(t.code, t.name, t.description) for t in types],
                cfg["LLM_URL"], timeout=cfg["LLM_TIMEOUT"],
                model=cfg["LLM_MODEL"])
        except llm.LlmUnavailable as exc:
            audit("LLM_PARSE", details=f"fail {exc}")
            flash("Модель недоступна — заполните поля вручную", "warning")
        else:
            s = llm.clean_suggestion(raw, {t.code: t.id for t in types},
                                     text=appeal.text.data)
            suggestion = _apply_suggestion(form, s)
            ms = int((time.monotonic() - started) * 1000)
            audit("LLM_PARSE", details=f"ok fields={len(s)} ms={ms} "
                                       f"model={cfg['LLM_MODEL']}")
        db.session.commit()
    return _register_page(form, appeal, suggestion)


@bp.route("/requests/<int:req_id>/vyzov", methods=["POST"])
@role_required(*STAFF_ROLES)
def vyzov(req_id):
    """Реквизиты справки-вызова: ФИО в дательном падеже, основание, период."""
    req = get_request(req_id)
    form = VyzovForm()
    if form.validate_on_submit():
        try:
            save_vyzov(req, g.user, form.name_dat.data, form.basis.data,
                       form.period_from.data, form.period_to.data)
            db.session.commit()
            flash("Данные справки-вызова сохранены", "success")
        except WorkflowError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    else:
        for errors in form.errors.values():
            for e in errors:
                flash(e, "danger")
    return redirect(url_for("staff.process", req_id=req.id))


@bp.route("/requests/<int:req_id>/print")
@role_required(*STAFF_ROLES)
def print_cert(req_id):
    req = get_request(req_id)
    if not req.can_print:
        abort(403)
    audit("CERT_PRINT", "request", req.id, req.number)
    db.session.commit()
    return render_template("staff/certificate.html", req=req,
                           cert=certificate_text(req))


@bp.route("/requests/<int:req_id>/pdf")
@role_required(*STAFF_ROLES)
def pdf(req_id):
    req = get_request(req_id)
    if not req.can_print:
        abort(403)
    audit("CERT_PDF", "request", req.id, req.number)
    db.session.commit()
    return Response(certificate_pdf(req), mimetype="application/pdf",
                    headers={"Content-Disposition":
                             f"inline; filename=spravka-{req.number}.pdf"})


@bp.route("/export.csv")
@role_required(*STAFF_ROLES)
def export_csv():
    rows = list(registry_rows(registry_query(request.args)))
    audit("EXPORT_CSV", details=f"rows={len(rows)}")
    db.session.commit()
    return Response(to_csv(REGISTRY_HEADER, rows), mimetype="text/csv",
                    headers={"Content-Disposition":
                             f"attachment; filename=reestr-{date.today()}.csv"})


@bp.route("/reports")
@role_required(*STAFF_ROLES)
def reports():
    d_from = parse_date(request.args.get("from"))
    d_to = parse_date(request.args.get("to"))
    stats = statistics(d_from, d_to)
    return render_template("staff/reports.html", s=stats,
                           d_from=d_from, d_to=d_to)


@bp.route("/reports.csv")
@role_required(*STAFF_ROLES)
def reports_csv():
    s = statistics(parse_date(request.args.get("from")),
                   parse_date(request.args.get("to")))
    rows = [[v["name"], v["total"], v["done"], v["late"]]
            for v in s["by_type"].values()]
    rows.append(["ИТОГО", s["total"], s["done"], s["late"]])
    audit("EXPORT_REPORT", details=f"total={s['total']}")
    db.session.commit()
    return Response(to_csv(["Тип справки", "Подано", "Подготовлено",
                            "С нарушением срока"], rows), mimetype="text/csv",
                    headers={"Content-Disposition":
                             f"attachment; filename=otchet-{date.today()}.csv"})
