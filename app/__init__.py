"""Фабрика приложения АИС учёта заявок студентов на получение справок."""
import os
import secrets
import sqlite3
import time
from datetime import date, datetime

import click
from flask import Flask, g, redirect, render_template, url_for
from flask_wtf.csrf import CSRFError, CSRFProtect

from .config import Config
from .models import (CHANNELS, DELIVERY, ROLE_ADMIN, ROLE_STAFF, ROLE_STUDENT,
                     VYZ_BASIS, Role, Status, db)
from .security import load_current_user, set_security_headers

csrf = CSRFProtect()

# Классификаторы, заполняемые при инициализации БД
ROLES = [(ROLE_STUDENT, "Студент"), (ROLE_STAFF, "Сотрудник деканата"),
         (ROLE_ADMIN, "Администратор")]
STATUSES = [("NEW", "Новая", False, "primary", 10),
            ("PREP", "Готовится", False, "warning", 20),
            ("READY", "Готова к выдаче", False, "success", 30),
            ("ISSUED", "Выдана", True, "dark", 40),
            ("REJ", "Отклонена", True, "danger", 50),
            ("CANC", "Отменена студентом", True, "secondary", 60)]


def init_classifiers():
    """Создание таблиц и заполнение справочников ролей и статусов."""
    db.create_all()
    for code, name in ROLES:
        if not Role.query.filter_by(code=code).first():
            db.session.add(Role(code=code, name=name))
    for code, name, final, css, order in STATUSES:
        if not Status.query.filter_by(code=code).first():
            db.session.add(Status(code=code, name=name, is_final=final,
                                  css=css, sort_order=order))
    db.session.commit()


def instance_secret(instance_path):
    """Случайный ключ сессии, созданный при первом запуске (права 600).

    Ключ по умолчанию в коде позволил бы подделать cookie сессии и войти
    под любым пользователем; поэтому без AIS_SECRET_KEY ключ хранится в
    файле экземпляра, а не в исходниках.
    """
    path = os.path.join(instance_path, "secret.key")
    if not os.path.exists(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(secrets.token_hex(32))
    with open(path, encoding="ascii") as fh:
        return fh.read().strip()


def create_app(config_class=Config):
    """Фабрика приложения: конфигурация, БД, маршруты, шаблоны, команды."""
    app = Flask(__name__, instance_path=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "instance"))
    app.config.from_object(config_class)
    os.makedirs(app.instance_path, exist_ok=True)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = instance_secret(app.instance_path)

    db.init_app(app)
    csrf.init_app(app)
    with app.app_context():
        # Недостающие таблицы (например, type_checks с 13.11.2026) создаются при
        # запуске: БД, созданная прежней версией, работает без ручного init-db.
        # Существующие таблицы и данные create_all не изменяет.
        db.create_all()

    from .views.admin import bp as admin_bp
    from .views.auth import bp as auth_bp
    from .views.staff import bp as staff_bp
    from .views.student import bp as student_bp
    for bp in (auth_bp, student_bp, staff_bp, admin_bp):
        app.register_blueprint(bp)

    app.before_request(load_current_user)
    app.after_request(set_security_headers)
    register_template_helpers(app)
    register_pages(app)
    register_cli(app)
    return app


def register_template_helpers(app):
    """Общие переменные и фильтры шаблонов Jinja2."""
    @app.context_processor
    def inject_globals():
        return {"today": date.today(), "DELIVERY": DELIVERY,
                "channels": CHANNELS, "VYZ_BASIS": VYZ_BASIS,
                "org_name": app.config["ORG_NAME"]}

    @app.template_filter("dt")
    def fmt_dt(value, fmt="%d.%m.%Y %H:%M"):
        return value.strftime(fmt) if value else "—"

    @app.template_filter("num")
    def fmt_num(value):
        """Десятичная запятая для отображения дробных показателей."""
        return "—" if value is None else str(value).replace(".", ",")


def register_pages(app):
    """Стартовая страница по роли и страницы ошибок 403, 404, CSRF."""
    @app.route("/")
    def index():
        if g.user is None:
            return redirect(url_for("auth.login"))
        target = {ROLE_STUDENT: "student.dashboard",
                  ROLE_STAFF: "staff.registry",
                  ROLE_ADMIN: "staff.registry"}[g.user.role_code]
        return redirect(url_for(target))

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("errors/error.html", code=403,
                               message="Доступ к разделу запрещён"), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("errors/error.html", code=404,
                               message="Страница не найдена"), 404

    @app.errorhandler(CSRFError)
    def csrf_error(_e):
        return render_template("errors/error.html", code=400,
                               message="Форма устарела или подделана "
                                       "(CSRF). Обновите страницу."), 400


def check_types(app, limit):
    """Команда check-types: проверить до limit новых заявок, записать итог в журнал."""
    from . import llm
    from .security import audit
    from .type_check import run_type_checks
    cfg = app.config
    if not cfg["LLM_URL"]:
        return "Проверка вида справки выключена: AIS_LLM_URL не задан"
    started = time.monotonic()
    try:
        checked, flagged = run_type_checks(
            cfg["LLM_URL"], cfg["LLM_TIMEOUT"], cfg["LLM_MODEL"], limit)
    except llm.LlmUnavailable as exc:
        db.session.rollback()
        audit("LLM_TYPE_CHECK", details=f"fail {exc}")
        db.session.commit()
        raise click.ClickException(
            f"Модель недоступна ({exc}); непроверенные заявки — "
            "при следующем запуске")
    ms = int((time.monotonic() - started) * 1000)
    audit("LLM_TYPE_CHECK", details=f"ok checked={checked} "
          f"flagged={flagged} ms={ms} model={cfg['LLM_MODEL']}")
    db.session.commit()
    return f"Проверено заявок: {checked}, с подсказкой: {flagged}"


def backup_db(app):
    """Команда backup-db: онлайн-копия файла SQLite (sqlite3 backup API); путь копии."""
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///") or uri == "sqlite:///:memory:":
        raise click.ClickException(
            "backup-db копирует только файл SQLite; для другой СУБД "
            "используйте её средства резервного копирования (например, pg_dump)")
    src_path = uri[len("sqlite:///"):]
    os.makedirs(app.config["BACKUP_DIR"], exist_ok=True)
    dst_path = os.path.join(app.config["BACKUP_DIR"], "ais-{:%Y%m%d-%H%M%S}"
                            ".sqlite3".format(datetime.now()))
    with sqlite3.connect(src_path) as src, sqlite3.connect(dst_path) as dst:
        src.backup(dst)
    return dst_path


def register_cli(app):
    """Команды flask: init-db, check-types (по расписанию), backup-db."""
    @app.cli.command("init-db")
    def init_db_cmd():
        """Создать таблицы и классификаторы."""
        init_classifiers()
        click.echo("БД инициализирована")

    @app.cli.command("check-types")
    @click.option("--limit", default=20, show_default=True,
                  help="Сколько заявок проверить за запуск")
    def check_types_cmd(limit):
        """Проверить вид справки по цели новых заявок локальной моделью."""
        click.echo(check_types(app, limit))

    @app.cli.command("backup-db")
    def backup_db_cmd():
        """Онлайн-копия БД SQLite в instance/backups (sqlite3 backup API)."""
        click.echo(f"Резервная копия: {backup_db(app)}")
