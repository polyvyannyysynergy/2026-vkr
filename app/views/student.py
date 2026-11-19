"""Blueprint student: личный кабинет студента."""
from flask import (Blueprint, Response, abort, flash, g, redirect,
                   render_template, url_for)

from ..certificate import certificate_pdf
from ..forms import RequestForm
from ..models import ROLE_STUDENT, ST_CANCELLED, CertType, Request, db
from ..security import audit, role_required
from ..services import WorkflowError, change_status, submit_request

bp = Blueprint("student", __name__, url_prefix="/student")


def own_request(req_id):
    """Заявка текущего студента; чужая — 404 (не раскрываем факт наличия)."""
    req = db.session.get(Request, req_id)
    if req is None or req.student.user_id != g.user.id:
        abort(404)
    return req


@bp.route("/")
@role_required(ROLE_STUDENT)
def dashboard():
    reqs = (Request.query.filter_by(student_id=g.user.student.id)
            .order_by(Request.created_at.desc()).all())
    counts = {}
    for r in reqs:
        counts[r.status.name] = counts.get(r.status.name, 0) + 1
    return render_template("student/dashboard.html", st=g.user.student,
                           recent=reqs[:5], counts=counts, total=len(reqs))


@bp.route("/new", methods=["GET", "POST"])
@role_required(ROLE_STUDENT)
def new_request():
    types = (CertType.query.filter_by(is_active=True)
             .order_by(CertType.sort_order).all())
    form = RequestForm()
    form.cert_type.choices = [(t.id, f"{t.name} — {t.lead_days} раб. дн.")
                              for t in types]
    if form.validate_on_submit():
        try:
            req = submit_request(g.user.student, form.cert_type.data,
                                 form.purpose.data, form.copies.data,
                                 form.delivery.data, form.post_address.data,
                                 form.comment.data, author=g.user)
        except WorkflowError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        else:
            flash(f"Заявка № {req.number} зарегистрирована. Плановая дата "
                  f"готовности: {req.planned_date:%d.%m.%Y}", "success")
            return redirect(url_for("student.request_card", req_id=req.id))
    return render_template("student/new.html", form=form, types=types)


@bp.route("/requests")
@role_required(ROLE_STUDENT)
def my_requests():
    reqs = (Request.query.filter_by(student_id=g.user.student.id)
            .order_by(Request.created_at.desc()).all())
    return render_template("student/requests.html", reqs=reqs)


@bp.route("/requests/<int:req_id>")
@role_required(ROLE_STUDENT)
def request_card(req_id):
    return render_template("student/card.html", req=own_request(req_id))


@bp.route("/requests/<int:req_id>/cancel", methods=["POST"])
@role_required(ROLE_STUDENT)
def cancel(req_id):
    req = own_request(req_id)
    try:
        change_status(req, ST_CANCELLED, g.user, "Отменена студентом")
        db.session.commit()
        flash(f"Заявка № {req.number} отменена", "info")
    except WorkflowError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("student.request_card", req_id=req.id))


@bp.route("/requests/<int:req_id>/pdf")
@role_required(ROLE_STUDENT)
def pdf(req_id):
    req = own_request(req_id)
    if not req.can_download:
        abort(403)
    audit("CERT_DOWNLOAD", "request", req.id, req.number)
    db.session.commit()
    return Response(certificate_pdf(req), mimetype="application/pdf",
                    headers={"Content-Disposition":
                             f"inline; filename=spravka-{req.number}.pdf"})
