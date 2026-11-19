"""Модуль безопасности: сессия пользователя, разграничение доступа, аудит."""
from datetime import datetime, timedelta
from functools import wraps

from flask import (abort, current_app, flash, g, has_request_context,
                   redirect, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .models import AUDIT_DETAILS_LEN, AuditLog, User, db

# хеш для несуществующего логина: проверка пароля занимает то же время,
# и по времени ответа нельзя узнать, есть ли такой логин
_DUMMY_HASH = generate_password_hash("dummy-password")


def load_current_user():
    """Загрузка пользователя сессии в g.user перед каждым запросом."""
    uid = session.get("uid")
    g.user = db.session.get(User, uid) if uid else None
    if g.user is not None and not g.user.is_active:
        session.clear()
        g.user = None


def audit(action, entity=None, entity_id=None, details=None, user=None,
          at=None):
    """Запись события в журнал аудита (без пароля и иных секретов)."""
    actor = user if user is not None else (
        g.get("user") if has_request_context() else None)
    db.session.add(AuditLog(
        user_id=actor.id if actor else None, action=action, entity=entity,
        entity_id=entity_id, details=(details or "")[:AUDIT_DETAILS_LEN],
        ip=request.remote_addr if has_request_context() else None,
        created_at=at or datetime.now()))


def authenticate(login, password):
    """Проверка учётных данных с учётом блокировки после неудачных попыток.

    Возвращает (user, ошибка). Ошибка не уточняет, что именно неверно.
    """
    cfg = current_app.config
    user = User.query.filter_by(login=login.strip().lower()).first()
    now = datetime.now()
    if user is None:
        check_password_hash(_DUMMY_HASH, password)
        audit("LOGIN_FAIL", "user", None, f"login={login[:40]}")
        return None, "Неверный логин или пароль"
    if user.locked_until and user.locked_until > now:
        audit("LOGIN_LOCKED", "user", user.id, user=user)
        return None, "Учётная запись временно заблокирована, повторите позже"
    if not user.is_active or not user.check_password(password):
        user.failed_logins += 1
        if user.failed_logins >= cfg["MAX_FAILED_LOGINS"]:
            user.locked_until = now + timedelta(minutes=cfg["LOCK_MINUTES"])
            user.failed_logins = 0
        audit("LOGIN_FAIL", "user", user.id, user=user)
        return None, "Неверный логин или пароль"
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    audit("LOGIN", "user", user.id, user=user)
    return user, None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            flash("Войдите в систему", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    """Декоратор: доступ только для перечисленных кодов ролей."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user.role_code not in roles:
                audit("ACCESS_DENIED", details=request.path)
                db.session.commit()
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def set_security_headers(response):
    """Заголовки, снижающие риск XSS, clickjacking и подмены типа."""
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'")
    return response
