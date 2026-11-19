"""Фоновая проверка «вид справки ↔ цель» локальной моделью.

Запускается командой `flask check-types` (по расписанию, например cron раз в
5 минут), а не при подаче заявки: студент модель не ждёт. Проверяются только
новые заявки без проверки; итог — запись TypeCheck, по которой сотрудник видит
подсказку. Модель не меняет ни вид справки, ни статус заявки.
"""
from . import llm
from .models import ST_NEW, CertType, Request, Status, TypeCheck, db


def pending(limit):
    """Новые (NEW) заявки, ещё не проверенные, в порядке поступления."""
    return (Request.query.join(Status, Request.status_id == Status.id)
            .filter(Status.code == ST_NEW)
            .outerjoin(TypeCheck, TypeCheck.request_id == Request.id)
            .filter(TypeCheck.id.is_(None))
            .order_by(Request.id).limit(limit).all())


def run_type_checks(url, timeout, model, limit=20):
    """Проверить до `limit` заявок; вернуть (проверено, с подсказкой).

    Каждая проверка сохраняется сразу: при недоступности модели
    (LlmUnavailable — пробрасывается) готовые записи остаются, остальные
    заявки будут проверены при следующем запуске. Непригодный ответ по
    одной заявке (LlmBadAnswer) записывается как проверка без подсказки,
    чтобы эта заявка не останавливала проверку остальных.
    """
    types = (CertType.query.filter_by(is_active=True)
             .order_by(CertType.sort_order).all())
    spec = [(t.code, t.name, t.description) for t in types]
    by_code = {t.code: t for t in types}
    checked = flagged = 0
    for req in pending(limit):
        chosen = req.cert_type.code
        try:
            raw = llm.check_type(req.purpose, req.student_comment, spec, url,
                                 timeout=timeout, model=model)
            need = llm.type_verdict(raw, chosen, by_code)
        except llm.LlmBadAnswer:
            need = None
        db.session.add(TypeCheck(
            request_id=req.id, model=model,
            suggested_type_id=by_code[need].id if need else None))
        db.session.commit()
        checked += 1
        flagged += need is not None
    return checked, flagged
