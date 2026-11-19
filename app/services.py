"""Модуль обработки заявок: нумерация, создание, переходы статусов."""
from datetime import datetime

from flask import current_app
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError

from .models import (CH_AIS, CHANNELS, DLV_EL, DLV_POST, OPEN_STATUSES,
                     ROLE_ADMIN, ROLE_STAFF, ROLE_STUDENT, ST_CANCELLED,
                     ST_ISSUED, ST_NEW, ST_PREP, ST_READY, ST_REJECTED,
                     VYZ_BASIS, CertType, Request, Status, StatusHistory, db)
from .security import audit
from .workdays import planned_date

# Граф допустимых переходов: (из, в) -> роли, которым переход разрешён
TRANSITIONS = {
    (ST_NEW, ST_PREP): {ROLE_STAFF, ROLE_ADMIN},
    (ST_NEW, ST_REJECTED): {ROLE_STAFF, ROLE_ADMIN},
    (ST_NEW, ST_CANCELLED): {ROLE_STUDENT},
    (ST_PREP, ST_READY): {ROLE_STAFF, ROLE_ADMIN},
    (ST_PREP, ST_REJECTED): {ROLE_STAFF, ROLE_ADMIN},
    (ST_READY, ST_ISSUED): {ROLE_STAFF, ROLE_ADMIN},
}
MIN_REJECT_REASON = 5  # символов в причине отклонения — её видит студент


class WorkflowError(Exception):
    """Нарушение правил обработки заявки."""


def status_by_code(code):
    return Status.query.filter_by(code=code).one()


def allowed_targets(req, role_code):
    """Коды статусов, в которые пользователь роли может перевести заявку."""
    return [to for (frm, to), roles in TRANSITIONS.items()
            if frm == req.status.code and role_code in roles]


def next_number(year):
    """Следующий номер заявки вида ГГГГ-NNNNN (сквозной в пределах года)."""
    prefix = f"{year}-"
    last = db.session.query(func.max(Request.number)).filter(
        Request.number.like(prefix + "%")).scalar()
    seq = int(last.split("-")[1]) + 1 if last else 1
    if seq > 99999:
        raise WorkflowError("Исчерпан диапазон номеров заявок года")
    return f"{prefix}{seq:05d}"


def _check_order(ctype, copies, delivery, post_address):
    """Правила заказа: тип доступен, число экземпляров, адрес, электронный вид."""
    if ctype is None or not ctype.is_active:
        raise WorkflowError("Тип справки недоступен для заказа")
    if not 1 <= copies <= ctype.max_copies:
        raise WorkflowError(
            f"Количество экземпляров: от 1 до {ctype.max_copies}")
    if delivery == DLV_POST and not (post_address or "").strip():
        raise WorkflowError("Для отправки почтой укажите адрес")
    if delivery == DLV_EL and not (ctype.printable and ctype.electronic):
        raise WorkflowError("Этот тип справки не выдаётся в электронном виде")


def create_request(student, cert_type_id, purpose, copies, delivery,
                   post_address=None, comment=None, author=None, now=None,
                   channel=CH_AIS, ext_number=None):
    """Регистрация новой заявки со статусом «Новая».

    channel — канал поступления: «AIS» — студент подал заявку в АИС сам;
    «ELK», «MFSO», «KUR» — заявку принял другой канал, и её регистрирует
    сотрудник деканата (ext_number — номер заявки в этом канале).
    """
    now = now or datetime.now()
    if channel not in CHANNELS:
        raise WorkflowError("Неизвестный канал поступления заявки")
    if channel != CH_AIS and author.role_code not in (ROLE_STAFF, ROLE_ADMIN):
        raise WorkflowError(
            "Заявку из ЕЛК, МФСО или от куратора регистрирует сотрудник")
    ctype = db.session.get(CertType, cert_type_id)
    _check_order(ctype, copies, delivery, post_address)
    new = status_by_code(ST_NEW)
    req = Request(
        number=next_number(now.year), student=student, cert_type=ctype,
        status=new, purpose=purpose.strip(), copies=copies,
        delivery=delivery, post_address=(post_address or "").strip() or None,
        student_comment=(comment or "").strip() or None, created_at=now,
        channel=channel, ext_number=(ext_number or "").strip() or None,
        planned_date=planned_date(now, ctype.lead_days,
                                  current_app.config["HOLIDAYS"]))
    db.session.add(req)
    db.session.flush()
    if channel == CH_AIS:
        note = "Заявка подана"
    else:
        note = f"Зарегистрирована сотрудником (канал: {CHANNELS[channel]}"
        note += f", № {req.ext_number})" if req.ext_number else ")"
    db.session.add(StatusHistory(request=req, from_status_id=None,
                                 to_status=new, changed_by=author.id,
                                 changed_at=now, comment=note))
    audit("REQUEST_CREATE", "request", req.id,
          f"{req.number} ({CHANNELS[channel]})", user=author, at=now)
    return req


def submit_request(*args, attempts=3, **kwargs):
    """create_request и фиксация транзакции. Если параллельная заявка заняла
    тот же номер (нарушение уникальности), транзакция откатывается и номер
    выдаётся заново."""
    for _ in range(attempts):
        try:
            req = create_request(*args, **kwargs)
            db.session.commit()
            return req
        except IntegrityError:
            db.session.rollback()
    raise WorkflowError("Не удалось присвоить номер заявки, повторите")


def change_status(req, to_code, user, comment=None, now=None, expected=None):
    """Перевод заявки в новый статус с проверкой графа переходов.

    expected — статус, который пользователь видел на странице; если заявку
    за это время перевёл другой сотрудник, переход не выполняется.
    """
    now = now or datetime.now()
    frm = req.status.code
    if expected and expected != frm:
        raise WorkflowError("Статус заявки уже изменил другой сотрудник: "
                            f"сейчас «{req.status.name}». Проверьте заявку "
                            "и повторите действие")
    roles = TRANSITIONS.get((frm, to_code))
    if roles is None:
        raise WorkflowError(f"Переход {frm} → {to_code} не предусмотрен")
    if user.role_code not in roles:
        raise WorkflowError("Недостаточно прав для этого перехода")
    if user.role_code == ROLE_STUDENT and req.student.user_id != user.id:
        raise WorkflowError("Заявка принадлежит другому студенту")
    comment = (comment or "").strip()
    if to_code == ST_READY and req.is_vyzov and not req.vyzov_complete:
        raise WorkflowError("Заполните данные справки-вызова: ФИО в дательном "
                            "падеже, основание и период")
    if to_code == ST_REJECTED and len(comment) < MIN_REJECT_REASON:
        raise WorkflowError("Укажите причину отклонения "
                            f"(не менее {MIN_REJECT_REASON} символов)")
    target = status_by_code(to_code)
    # Два запроса к одной заявке одновременно: статус меняется условным
    # UPDATE «где статус всё ещё прежний»; второй запрос получает сообщение,
    # а не второй переход в истории.
    claimed = db.session.execute(
        update(Request).where(Request.id == req.id,
                              Request.status_id == req.status.id)
        .values(status_id=target.id)
        .execution_options(synchronize_session=False)).rowcount
    if not claimed:
        raise WorkflowError("Заявку одновременно обработал другой "
                            "сотрудник — обновите страницу")
    if to_code == ST_REJECTED:
        req.reject_reason = comment
    if to_code == ST_PREP:
        req.operator_id = user.id
    if to_code == ST_READY:
        req.ready_at = now
    if target.is_final:
        req.closed_at = now
    db.session.add(StatusHistory(request=req, from_status=req.status,
                                 to_status=target, changed_by=user.id,
                                 changed_at=now, comment=comment or None))
    req.status = target
    audit("STATUS_CHANGE", "request", req.id,
          f"{req.number}: {frm} -> {to_code}", user=user, at=now)
    return req


def save_vyzov(req, user, name_dat, basis, period_from, period_to, now=None):
    """Реквизиты справки-вызова (форма приказа Минобрнауки России № 1368)."""
    now = now or datetime.now()
    if not req.is_vyzov:
        raise WorkflowError("Заявка не на справку-вызов")
    if req.status.code not in OPEN_STATUSES:
        raise WorkflowError("Данные меняются только до готовности справки")
    if basis not in VYZ_BASIS:
        raise WorkflowError("Неизвестное основание")
    if not (period_from and period_to) or period_to < period_from:
        raise WorkflowError("Дата окончания раньше даты начала")
    req.name_dat = name_dat.strip()
    req.basis, req.period_from, req.period_to = basis, period_from, period_to
    audit("VYZOV_DATA", "request", req.id,
          f"{req.number}: {period_from:%d.%m.%Y}–{period_to:%d.%m.%Y}",
          user=user, at=now)
    return req


# Подсказка ФИО в дательном падеже для справки-вызова. Правила покрывают
# типовые русские ФИО; результат проверяет и при необходимости правит
# сотрудник (поле формы редактируемое).
_NAME_EXCEPTIONS = {"Павел": "Павлу", "Пётр": "Петру", "Петр": "Петру",
                    "Лев": "Льву"}


def _dat_surname(s, female):
    if female:
        for end, rep in (("ская", "ской"), ("цкая", "цкой"), ("ова", "овой"),
                         ("ёва", "ёвой"), ("ева", "евой"), ("ина", "иной"),
                         ("ына", "ыной"), ("ая", "ой")):
            if s.endswith(end):
                return s[:-len(end)] + rep
        return s
    for end, rep in (("ский", "скому"), ("цкий", "цкому"), ("ий", "ому"),
                     ("ой", "ому"), ("ый", "ому")):
        if s.endswith(end):
            return s[:-len(end)] + rep
    if s.endswith(("ых", "их", "ко", "о", "е", "и", "у", "ю")):
        return s
    if s.endswith("а"):
        return s[:-1] + "е"
    return s + "у"


def _dat_first(n, female):
    if n in _NAME_EXCEPTIONS:
        return _NAME_EXCEPTIONS[n]
    if n.endswith("ия"):
        return n[:-1] + "и"
    if n.endswith(("а", "я")):
        return n[:-1] + "е"
    if female:
        return n
    if n.endswith("й"):
        return n[:-1] + "ю"
    if n.endswith("ь"):
        return n[:-1] + "ю"
    return n + "у"


def is_female(full_name):
    """Род по отчеству: …вна, …чна, «… кызы» / «… гызы» (слитно или
    отдельным словом); без отчества — мужской."""
    parts = full_name.split()
    if len(parts) == 4 and parts[3].lower() in ("кызы", "гызы"):
        return True
    return len(parts) == 3 and parts[2].lower().endswith(("на", "кызы", "гызы"))


def dative_name(full_name):
    """«Фамилия Имя Отчество» → дательный падеж (род — по отчеству)."""
    parts = full_name.split()
    if len(parts) != 3:
        return full_name
    sur, first, patr = parts
    female = is_female(full_name)
    patr_dat = patr[:-1] + "е" if patr.endswith("на") else (
        patr + "у" if patr.endswith("ич") else patr)
    return " ".join((_dat_surname(sur, female), _dat_first(first, female),
                     patr_dat))
