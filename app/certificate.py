"""Модуль формирования справки: текст по шаблону, печатная форма и PDF."""
import io
import os

from flask import current_app
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .models import (FUNDING, STUDY_FORMS, STUDY_FORMS_DAT, VYZ_ARTICLE,
                     VYZ_BASIS)
from .services import is_female

MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря")


def ru_date(d):
    return f"«{d.day:02d}» {MONTHS[d.month - 1]} {d.year} г."


SIGNER = ("Руководитель организации, осуществляющей образовательную "
          "деятельность, иное уполномоченное им должностное лицо")


def vyzov_text(req):
    """Справка-вызов по форме приказа Минобрнауки России от 19.12.2013
    № 1368 (основная часть и отрывная справка-подтверждение)."""
    st, cfg = req.student, current_app.config
    d1, d2 = req.period_from.strftime("%d.%m.%Y"), req.period_to.strftime("%d.%m.%Y")
    main = [
        f"Работодателю {req.purpose}.",
        f"В соответствии со статьей {VYZ_ARTICLE} Трудового кодекса Российской "
        f"Федерации {req.name_dat}, обучающемуся по "
        f"{STUDY_FORMS_DAT[st.study_form]} форме обучения на {st.course} курсе, "
        f"предоставляются гарантии и компенсации для "
        f"{VYZ_BASIS[req.basis]} с {d1} по {d2} продолжительностью "
        f"{req.vyzov_days} календарных дней.",
        f"{cfg['ORG_NAME']} имеет свидетельство о государственной аккредитации, "
        f"выданное: {cfg['ORG_ACCREDITATION']}, по образовательной программе "
        f"высшего образования по направлению подготовки {st.direction}.",
    ]
    verb = "находилась" if is_female(st.user.full_name) else "находился"
    stub = [f"{st.user.full_name} {verb} в {cfg['ORG_NAME_PREP']} "
            f"с {d1} по {d2}."]
    return {
        "vyzov": True,
        "org": cfg["ORG_NAME"],
        "title": "СПРАВКА-ВЫЗОВ",
        "number": req.number,
        "date": ru_date((req.ready_at or req.created_at).date()),
        "paragraphs": main,
        "stub": stub,
        "signer": SIGNER,
        "copies": req.copies,
    }


def certificate_text(req):
    """Абзацы справки, общие для HTML- и PDF-формы."""
    if req.is_vyzov:
        return vyzov_text(req)
    st = req.student
    org = current_app.config["ORG_NAME"]
    org_gen = current_app.config["ORG_NAME_GEN"]
    # формулировки без указания рода: справка не зависит от пола студента
    body = (
        f"Настоящая справка подтверждает, что {st.user.full_name} "
        f"(дата рождения {st.birth_date.strftime('%d.%m.%Y')}) имеет статус "
        f"обучающегося {org_gen}: {st.course} курс, "
        f"{STUDY_FORMS[st.study_form]} форма обучения, "
        f"направление подготовки {st.direction}, {st.faculty}, "
        f"группа {st.group_code}, основа обучения — {FUNDING[st.funding]}.")
    order = (f"Основание: приказ о зачислении № {st.enroll_order} от "
             f"{st.enroll_date.strftime('%d.%m.%Y')}. Нормативный срок "
             f"окончания обучения — {st.graduation_date.strftime('%d.%m.%Y')}.")
    purpose = f"Справка выдана для предоставления: {req.purpose}."
    return {
        "org": org,
        "title": req.cert_type.name.upper(),
        "number": req.number,
        "date": ru_date((req.ready_at or req.created_at).date()),
        "paragraphs": [body, order, purpose],
        "copies": req.copies,
    }


def _register_fonts():
    font_dir = os.path.join(current_app.static_folder, "fonts")
    if "AisSerif" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("AisSerif",
                                       os.path.join(font_dir, "DejaVuSerif.ttf")))
        pdfmetrics.registerFont(TTFont(
            "AisSerif-Bold", os.path.join(font_dir, "DejaVuSerif-Bold.ttf")))


def _wrap(text, font, size, width):
    """Перенос строки по словам под заданную ширину; слово шире строки
    (например, длинная ссылка в цели справки) делится по символам."""
    def fits(s):
        return pdfmetrics.stringWidth(s, font, size) <= width
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if fits(trial):
            line = trial
            continue
        if line:
            lines.append(line)
        while not fits(word):
            cut = len(word) - 1
            while cut > 1 and not fits(word[:cut]):
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        line = word
    if line:
        lines.append(line)
    return lines


def certificate_pdf(req):
    """PDF-файл справки (A4) в виде байтов."""
    _register_fonts()
    data = certificate_text(req)
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.setTitle(f"Справка {data['number']}")
    w, h = A4
    left, width, y = 25 * mm, w - 45 * mm, h - 25 * mm
    if data.get("vyzov"):
        _vyzov_pdf(pdf, data, w, left, width, y)
        pdf.showPage()
        pdf.save()
        return buf.getvalue()
    pdf.setFont("AisSerif-Bold", 13)
    pdf.drawCentredString(w / 2, y, data["org"])
    y -= 7 * mm
    pdf.setFont("AisSerif", 10)
    pdf.drawCentredString(w / 2, y, "Деканат факультета")
    y -= 4 * mm
    pdf.line(left, y, left + width, y)
    y -= 14 * mm
    pdf.setFont("AisSerif-Bold", 14)
    pdf.drawCentredString(w / 2, y, data["title"])
    y -= 7 * mm
    pdf.setFont("AisSerif", 11)
    pdf.drawCentredString(w / 2, y, f"№ {data['number']} от {data['date']}")
    y -= 14 * mm
    for par in data["paragraphs"]:
        for line in _wrap(par, "AisSerif", 12, width):
            pdf.drawString(left, y, line)
            y -= 6.5 * mm
        y -= 3 * mm
    y -= 18 * mm
    pdf.drawString(left, y, "Декан факультета")
    pdf.drawString(left + 70 * mm, y, "________________ / ________________")
    y -= 6 * mm
    pdf.setFont("AisSerif", 8)
    pdf.drawString(left + 78 * mm, y, "подпись")
    pdf.drawString(left + 118 * mm, y, "расшифровка")
    y -= 12 * mm
    pdf.setFont("AisSerif", 11)
    pdf.drawString(left, y, "М.П.")
    pdf.setFont("AisSerif", 8)
    pdf.drawString(left, 15 * mm, "Сформировано АИС учёта заявок на справки. "
                   f"Экземпляров: {data['copies']}. Демонстрационные данные.")
    pdf.showPage()
    pdf.save()
    return buf.getvalue()


def _sign_block(pdf, data, left, width, y):
    for line in _wrap(data["signer"], "AisSerif", 10, 80 * mm):
        pdf.setFont("AisSerif", 10)
        pdf.drawString(left, y, line)
        y -= 4.5 * mm
    pdf.drawString(left + 88 * mm, y + 4.5 * mm,
                   "____________ / ______________")
    y -= 4 * mm
    pdf.setFont("AisSerif", 11)
    pdf.drawString(left, y, "М.П.")
    return y - 8 * mm


def _paragraphs(pdf, paragraphs, left, width, y, size=12):
    pdf.setFont("AisSerif", size)
    for par in paragraphs:
        for line in _wrap(par, "AisSerif", size, width):
            pdf.drawString(left, y, line)
            y -= 6 * mm
        y -= 2 * mm
    return y


def _vyzov_pdf(pdf, data, w, left, width, y):
    """Справка-вызов: основная часть, линия отрыва, справка-подтверждение."""
    pdf.setFont("AisSerif-Bold", 14)
    pdf.drawCentredString(w / 2, y, data["title"])
    y -= 6 * mm
    pdf.setFont("AisSerif", 10)
    for line in (f"от {data['date']} № {data['number']},",
                 "дающая право на предоставление гарантий и компенсаций",
                 "работникам, совмещающим работу с получением образования"):
        pdf.drawCentredString(w / 2, y, line)
        y -= 4.5 * mm
    y -= 6 * mm
    y = _paragraphs(pdf, data["paragraphs"], left, width, y)
    y = _sign_block(pdf, data, left, width, y - 6 * mm)
    pdf.setDash(2, 2)
    pdf.line(left, y, left + width, y)
    pdf.setDash()
    pdf.setFont("AisSerif", 8)
    pdf.drawCentredString(w / 2, y - 3.5 * mm, "линия отрыва")
    y -= 12 * mm
    y = _paragraphs(pdf, data["stub"], left, width, y)
    _sign_block(pdf, data, left, width, y - 6 * mm)
    pdf.setFont("AisSerif", 8)
    pdf.drawString(left, 15 * mm, "Сформировано АИС учёта заявок на справки "
                   "по форме приказа Минобрнауки России № 1368. "
                   f"Экземпляров: {data['copies']}. Демонстрационные данные.")
