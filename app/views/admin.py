"""Blueprint admin: справочник типов справок, пользователи, журнал аудита."""
from datetime import datetime

from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, url_for)

from ..forms import CertTypeForm, UserForm
from ..models import (ROLE_ADMIN, ROLE_STUDENT, AuditLog, CertType, Role,
                      Student, User, db)
from ..security import audit, role_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/types")
@role_required(ROLE_ADMIN)
def types():
    items = CertType.query.order_by(CertType.sort_order).all()
    return render_template("admin/types.html", items=items)


@bp.route("/types/new", methods=["GET", "POST"])
@bp.route("/types/<int:type_id>", methods=["GET", "POST"])
@role_required(ROLE_ADMIN)
def type_edit(type_id=None):
    item = db.session.get(CertType, type_id) if type_id else None
    if type_id and item is None:
        abort(404)
    form = CertTypeForm(obj=item)
    if form.validate_on_submit():
        dup = CertType.query.filter_by(code=form.code.data).first()
        if dup and dup is not item:
            flash("Код типа справки уже используется", "danger")
        else:
            if item is None:
                item = CertType()
                db.session.add(item)
            form.populate_obj(item)
            db.session.flush()
            audit("CERT_TYPE_SAVE", "cert_type", item.id,
                  f"{item.code}: {item.lead_days} дн., active={item.is_active}")
            db.session.commit()
            flash("Тип справки сохранён", "success")
            return redirect(url_for("admin.types"))
    return render_template("admin/type_edit.html", form=form, item=item)


@bp.route("/users")
@role_required(ROLE_ADMIN)
def users():
    role = request.args.get("role")
    q = User.query.join(Role)
    if role:
        q = q.filter(Role.code == role)
    return render_template("admin/users.html",
                           items=q.order_by(Role.id, User.full_name).all(),
                           roles=Role.query.all(), role=role,
                           now=datetime.now())


@bp.route("/users/new", methods=["GET", "POST"])
@role_required(ROLE_ADMIN)
def user_new():
    form = UserForm()
    form.role.choices = [(r.code, r.name) for r in Role.query.all()]
    if form.validate_on_submit():
        role = Role.query.filter_by(code=form.role.data).one()
        need = [form.record_book_no, form.birth_date, form.faculty,
                form.direction, form.group_code, form.course,
                form.enroll_order, form.enroll_date, form.graduation_date]
        if User.query.filter_by(login=form.login.data).first():
            flash("Логин занят", "danger")
        elif (role.code == ROLE_STUDENT and form.record_book_no.data
              and Student.query.filter_by(
                  record_book_no=form.record_book_no.data.strip()).first()):
            flash("Студент с таким номером зачётной книжки уже есть", "danger")
        elif role.code == ROLE_STUDENT and any(not f.data for f in need):
            flash("Для студента заполните все поля карточки", "danger")
        else:
            user = User(login=form.login.data, full_name=form.full_name.data,
                        email=form.email.data or None, role=role)
            user.set_password(form.password.data)
            db.session.add(user)
            if role.code == ROLE_STUDENT:
                db.session.add(Student(
                    user=user, record_book_no=form.record_book_no.data,
                    birth_date=form.birth_date.data, faculty=form.faculty.data,
                    direction=form.direction.data,
                    group_code=form.group_code.data, course=form.course.data,
                    study_form=form.study_form.data, funding=form.funding.data,
                    enroll_order=form.enroll_order.data,
                    enroll_date=form.enroll_date.data,
                    graduation_date=form.graduation_date.data))
            db.session.flush()
            audit("USER_CREATE", "user", user.id, f"{user.login} ({role.code})")
            db.session.commit()
            flash(f"Пользователь {user.login} создан", "success")
            return redirect(url_for("admin.users"))
    return render_template("admin/user_new.html", form=form)


@bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@role_required(ROLE_ADMIN)
def user_toggle(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if user.id == g.user.id:
        flash("Нельзя заблокировать собственную учётную запись", "danger")
    else:
        user.is_active = not user.is_active
        user.locked_until = None
        audit("USER_TOGGLE", "user", user.id, f"active={user.is_active}")
        db.session.commit()
        flash(f"{user.login}: {'активна' if user.is_active else 'заблокирована'}",
              "info")
    return redirect(url_for("admin.users"))


@bp.route("/audit")
@role_required(ROLE_ADMIN)
def audit_log():
    page = request.args.get("page", 1, type=int)
    action = request.args.get("action", "")
    q = AuditLog.query
    if action:
        q = q.filter(AuditLog.action == action)
    pager = q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).paginate(
        page=page, per_page=30, error_out=False)
    actions = [a[0] for a in db.session.query(AuditLog.action).distinct()
               .order_by(AuditLog.action)]
    return render_template("admin/audit.html", pager=pager, actions=actions,
                           action=action)
