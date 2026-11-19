"""Blueprint auth: вход, выход, смена пароля."""
from urllib.parse import urlsplit

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   session, url_for)

from ..forms import LoginForm, PasswordForm
from ..models import db
from ..security import audit, authenticate, login_required

bp = Blueprint("auth", __name__)


def safe_next(nxt):
    """Адрес возврата после входа — только локальный путь этого сайта.

    Отсекаются «//хост», обратная косая черта и управляющие символы: браузер
    отбрасывает табуляцию и перевод строки, и «/%09/evil.example» стал бы
    «//evil.example».
    """
    if (not nxt.startswith("/") or "\\" in nxt
            or any(ord(c) < 32 or ord(c) == 127 for c in nxt)):
        return None
    parts = urlsplit(nxt)
    if parts.scheme or parts.netloc or nxt.startswith("//"):
        return None
    return nxt


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None:
        return redirect(url_for("index"))
    form = LoginForm()
    if form.validate_on_submit():
        user, error = authenticate(form.login.data, form.password.data)
        db.session.commit()
        if user:
            session.clear()
            session["uid"] = user.id
            session.permanent = True
            nxt = safe_next(request.args.get("next", ""))
            return redirect(nxt or url_for("index"))
        flash(error, "danger")
    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    audit("LOGOUT", "user", g.user.id)
    db.session.commit()
    session.clear()
    flash("Сеанс завершён", "info")
    return redirect(url_for("auth.login"))


@bp.route("/password", methods=["GET", "POST"])
@login_required
def password():
    form = PasswordForm()
    if form.validate_on_submit():
        if not g.user.check_password(form.old.data):
            flash("Текущий пароль указан неверно", "danger")
        else:
            g.user.set_password(form.new.data)
            audit("PASSWORD_CHANGE", "user", g.user.id)
            db.session.commit()
            flash("Пароль изменён", "success")
            return redirect(url_for("index"))
    return render_template("auth/password.html", form=form)
