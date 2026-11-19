"""Модуль отчётности: выборка реестра по фильтрам, статистика, экспорт CSV."""
import csv
import io
from datetime import date, datetime, time

from flask import current_app
from sqlalchemy import or_

from .models import CHANNELS, CertType, Request, Status, Student, User
from .services import OPEN_STATUSES
from .workdays import workdays_between


def parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def registry_query(args, today=None):
    """Запрос к реестру заявок с фильтрами из параметров GET."""
    today = today or date.today()
    q = (Request.query.join(Student).join(User, Student.user_id == User.id)
         .join(Status).join(CertType))
    text = (args.get("q") or "").strip()
    if text:
        like = f"%{text}%"
        q = q.filter(or_(Request.number.like(like), User.full_name.like(like),
                         Student.record_book_no.like(like)))
    if args.get("status"):
        q = q.filter(Status.code == args["status"])
    if args.get("type"):
        q = q.filter(CertType.code == args["type"])
    if args.get("channel"):
        q = q.filter(Request.channel == args["channel"])
    if args.get("group"):
        q = q.filter(Student.group_code == args["group"])
    d_from, d_to = parse_date(args.get("from")), parse_date(args.get("to"))
    if d_from:
        q = q.filter(Request.created_at >= datetime.combine(d_from, time.min))
    if d_to:
        q = q.filter(Request.created_at <= datetime.combine(d_to, time.max))
    if args.get("overdue") == "1":
        q = q.filter(Status.code.in_(OPEN_STATUSES),
                     Request.planned_date < today)
    return q.order_by(Request.created_at.desc())


def statistics(d_from=None, d_to=None, today=None):
    """Сводные показатели работы с заявками за период."""
    today = today or date.today()
    hol = current_app.config["HOLIDAYS"]
    q = Request.query
    if d_from:
        q = q.filter(Request.created_at >= datetime.combine(d_from, time.min))
    if d_to:
        q = q.filter(Request.created_at <= datetime.combine(d_to, time.max))
    rows = q.all()
    by_type, by_status = {}, {}
    by_channel = {code: {"name": name, "total": 0, "done": 0, "late": 0}
                  for code, name in CHANNELS.items()}
    for t in CertType.query.order_by(CertType.sort_order):
        by_type[t.code] = {"name": t.name, "total": 0, "done": 0, "late": 0}
    for s in Status.query.order_by(Status.sort_order):
        by_status[s.code] = {"name": s.name, "css": s.css, "total": 0}
    proc_days, proc_work, overdue, late = [], [], [], 0
    for r in rows:
        by_type[r.cert_type.code]["total"] += 1
        by_status[r.status.code]["total"] += 1
        by_channel[r.channel]["total"] += 1
        if r.ready_at:
            by_type[r.cert_type.code]["done"] += 1
            by_channel[r.channel]["done"] += 1
            proc_days.append((r.ready_at - r.created_at).total_seconds() / 86400)
            proc_work.append(workdays_between(r.created_at, r.ready_at, hol))
            if r.ready_at.date() > r.planned_date:
                late += 1
                by_type[r.cert_type.code]["late"] += 1
                by_channel[r.channel]["late"] += 1
        elif r.is_overdue(today):
            overdue.append(r)
    done = len(proc_days)
    return {
        "total": len(rows),
        "by_type": by_type,
        "by_status": by_status,
        "by_channel": by_channel,
        "done": done,
        "avg_days": round(sum(proc_days) / done, 1) if done else None,
        "avg_workdays": round(sum(proc_work) / done, 1) if done else None,
        "late": late,
        "on_time_pct": round(100 * (done - late) / done, 1) if done else None,
        "overdue": sorted(overdue, key=lambda r: r.planned_date),
    }


REGISTRY_HEADER = ["Номер", "Дата подачи", "Студент", "Группа", "Тип справки",
                   "Канал", "№ в канале", "Экз.", "Способ получения", "Статус",
                   "Плановая дата", "Дата готовности", "Оператор"]


def registry_rows(requests):
    for r in requests:
        yield [r.number, r.created_at.strftime("%d.%m.%Y %H:%M"),
               r.student.user.full_name, r.student.group_code, r.cert_type.name,
               r.channel_name, r.ext_number or "", r.copies, r.delivery_name, r.status.name,
               r.planned_date.strftime("%d.%m.%Y"),
               r.ready_at.strftime("%d.%m.%Y") if r.ready_at else "",
               r.operator.full_name if r.operator else ""]


def csv_cell(value):
    """Текст, начинающийся с = + - @ (или табуляции), Excel исполнил бы как
    формулу; такой ячейке предшествует апостроф. Числа — как есть."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def to_csv(header, rows):
    """CSV в UTF-8 с BOM и разделителем «;» — открывается в MS Excel."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows([csv_cell(v) for v in row] for row in rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")
