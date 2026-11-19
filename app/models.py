"""Модель данных АИС: 9 таблиц базы данных SQLite."""
from datetime import date, datetime

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

# Коды классификаторов (см. раздел 2.2.2 ВКР)
ROLE_STUDENT, ROLE_STAFF, ROLE_ADMIN = "STUDENT", "STAFF", "ADMIN"
ST_NEW, ST_PREP, ST_READY = "NEW", "PREP", "READY"
ST_REJECTED, ST_ISSUED, ST_CANCELLED = "REJ", "ISSUED", "CANC"
OPEN_STATUSES = (ST_NEW, ST_PREP)                    # заявка ещё в работе
PRINTABLE_STATUSES = (ST_PREP, ST_READY, ST_ISSUED)  # справку можно печатать
CH_AIS = "AIS"                                       # заявку подал студент в АИС
DLV_EL, DLV_DEAN, DLV_POST = "EL", "DEAN", "POST"    # способы получения
AUDIT_DETAILS_LEN = 500                              # длина поля details журнала
DELIVERY = {"EL": "Электронно (PDF в кабинете)",
            "DEAN": "Лично в деканате",
            "POST": "Почтой России"}
STUDY_FORMS = {"OCH": "очная", "OZ": "очно-заочная", "ZAO": "заочная"}
FUNDING = {"BUD": "бюджет", "DOG": "договор"}
# Каналы поступления заявки: студент подаёт в АИС сам; заявки, принятые через
# ЕЛК, МФСО или куратора, регистрирует сотрудник деканата — единый реестр
CHANNELS = {"AIS": "АИС", "ELK": "ЕЛК", "MFSO": "МФСО", "KUR": "Куратор"}
# Справка-вызов (форма — приказ Минобрнауки России от 19.12.2013 № 1368)
VYZ_CODE = "VYZ"
VYZ_ARTICLE = "173"  # ст. 173 ТК РФ: высшее образование (бакалавриат и др.)
VYZ_BASIS = {"PA": "прохождения промежуточной аттестации",
             "GIA": "прохождения государственной итоговой аттестации",
             "VKR": "подготовки и защиты выпускной квалификационной работы",
             "GEX": "сдачи итоговых государственных экзаменов"}
STUDY_FORMS_DAT = {"OCH": "очной", "OZ": "очно-заочной", "ZAO": "заочной"}


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)
    name = db.Column(db.String(60), nullable=False)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(40), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120))
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    failed_logins = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    last_login_at = db.Column(db.DateTime)

    role = db.relationship("Role")
    student = db.relationship("Student", back_populates="user", uselist=False)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    @property
    def role_code(self):
        return self.role.code

    @property
    def short_name(self):
        """Фамилия и инициалы: «Иванова М.С.»."""
        parts = self.full_name.split()
        return parts[0] + " " + "".join(p[0] + "." for p in parts[1:3])


class Student(db.Model):
    __tablename__ = "students"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                        unique=True, nullable=False)
    record_book_no = db.Column(db.String(20), unique=True, nullable=False)
    birth_date = db.Column(db.Date, nullable=False)
    faculty = db.Column(db.String(120), nullable=False)
    direction = db.Column(db.String(160), nullable=False)
    group_code = db.Column(db.String(20), nullable=False, index=True)
    course = db.Column(db.Integer, nullable=False)
    study_form = db.Column(db.String(3), nullable=False)
    funding = db.Column(db.String(3), nullable=False)
    enroll_order = db.Column(db.String(40), nullable=False)
    enroll_date = db.Column(db.Date, nullable=False)
    graduation_date = db.Column(db.Date, nullable=False)

    user = db.relationship("User", back_populates="student")

    @property
    def study_form_name(self):
        return STUDY_FORMS.get(self.study_form, self.study_form)


class CertType(db.Model):
    __tablename__ = "cert_types"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)
    name = db.Column(db.String(160), nullable=False)
    lead_days = db.Column(db.Integer, nullable=False)  # срок, рабочих дней
    max_copies = db.Column(db.Integer, default=3, nullable=False)
    printable = db.Column(db.Boolean, default=True, nullable=False)
    # можно ли выдать электронно (PDF в кабинете); справке-вызову нужен
    # бумажный оригинал с подписью и печатью
    electronic = db.Column(db.Boolean, default=True, nullable=False)
    description = db.Column(db.String(400))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=100, nullable=False)


class Status(db.Model):
    __tablename__ = "statuses"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)
    name = db.Column(db.String(40), nullable=False)
    is_final = db.Column(db.Boolean, default=False, nullable=False)
    css = db.Column(db.String(20), default="secondary", nullable=False)
    sort_order = db.Column(db.Integer, default=100, nullable=False)


class Request(db.Model):
    __tablename__ = "requests"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(10), unique=True, nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"),
                           nullable=False, index=True)
    cert_type_id = db.Column(db.Integer, db.ForeignKey("cert_types.id"),
                             nullable=False)
    status_id = db.Column(db.Integer, db.ForeignKey("statuses.id"),
                          nullable=False, index=True)
    operator_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    purpose = db.Column(db.String(200), nullable=False)
    copies = db.Column(db.Integer, default=1, nullable=False)
    delivery = db.Column(db.String(4), nullable=False)
    post_address = db.Column(db.String(250))
    student_comment = db.Column(db.String(400))
    channel = db.Column(db.String(4), default=CH_AIS, nullable=False,
                        index=True)                   # канал поступления
    ext_number = db.Column(db.String(30))             # № во внешнем канале
    # реквизиты справки-вызова (заполняет сотрудник по учебному графику)
    name_dat = db.Column(db.String(120))              # ФИО в дательном падеже
    basis = db.Column(db.String(4))                   # код из VYZ_BASIS
    period_from = db.Column(db.Date)
    period_to = db.Column(db.Date)
    reject_reason = db.Column(db.String(400))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    planned_date = db.Column(db.Date, nullable=False)
    ready_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)

    student = db.relationship("Student")
    cert_type = db.relationship("CertType")
    status = db.relationship("Status")
    operator = db.relationship("User")
    history = db.relationship("StatusHistory", back_populates="request",
                              order_by="StatusHistory.changed_at",
                              cascade="all, delete-orphan")
    # итог фоновой проверки «вид справки ↔ цель» локальной моделью
    type_check = db.relationship("TypeCheck", uselist=False, lazy="selectin",
                                 cascade="all, delete-orphan")

    @property
    def delivery_name(self):
        return DELIVERY.get(self.delivery, self.delivery)

    @property
    def channel_name(self):
        return CHANNELS.get(self.channel, self.channel)

    def is_overdue(self, today=None):
        """Заявка в работе (новая или готовится), а плановая дата прошла."""
        return (self.status.code in OPEN_STATUSES
                and self.planned_date < (today or date.today()))

    @property
    def can_print(self):
        """Печать в АИС: тип печатается, статус допускает, у справки-вызова
        заполнены сведения (иначе печатать нечего)."""
        return (self.cert_type.printable
                and self.status.code in PRINTABLE_STATUSES
                and (not self.is_vyzov or self.vyzov_complete))

    @property
    def can_download(self):
        """Студент скачивает PDF: электронный способ, тип выдаётся
        электронно, справка готова или выдана."""
        return (self.delivery == DLV_EL and self.cert_type.printable
                and self.cert_type.electronic
                and self.status.code in (ST_READY, ST_ISSUED))

    @property
    def is_vyzov(self):
        return self.cert_type.code == VYZ_CODE

    @property
    def vyzov_complete(self):
        return bool(self.name_dat and self.basis in VYZ_BASIS
                    and self.period_from and self.period_to
                    and self.period_from <= self.period_to)

    @property
    def vyzov_days(self):
        """Продолжительность в календарных днях (включая обе даты)."""
        if not (self.period_from and self.period_to):
            return None
        return (self.period_to - self.period_from).days + 1


class StatusHistory(db.Model):
    __tablename__ = "status_history"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("requests.id"),
                           nullable=False, index=True)
    from_status_id = db.Column(db.Integer, db.ForeignKey("statuses.id"))
    to_status_id = db.Column(db.Integer, db.ForeignKey("statuses.id"),
                             nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey("users.id"),
                           nullable=False)
    changed_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    comment = db.Column(db.String(400))

    request = db.relationship("Request", back_populates="history")
    from_status = db.relationship("Status", foreign_keys=[from_status_id])
    to_status = db.relationship("Status", foreign_keys=[to_status_id])
    author = db.relationship("User")


class TypeCheck(db.Model):
    """Итог проверки «вид справки ↔ цель» локальной моделью.

    Хранится только вывод: какой вид модель сочла нужным (или null, если
    выбранный подходит). Текст цели не копируется; заявку модель не меняет.
    """
    __tablename__ = "type_checks"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("requests.id"),
                           unique=True, nullable=False)
    suggested_type_id = db.Column(db.Integer, db.ForeignKey("cert_types.id"))
    checked_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    model = db.Column(db.String(60))

    suggested_type = db.relationship("CertType")


class AuditLog(db.Model):
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(40), nullable=False, index=True)
    entity = db.Column(db.String(30))
    entity_id = db.Column(db.Integer)
    details = db.Column(db.String(AUDIT_DETAILS_LEN))
    ip = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    user = db.relationship("User")
