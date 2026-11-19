"""Заполнение БД демонстрационными данными (вымышленные студенты и заявки).

Запуск:  python seed.py            — пересоздать БД с данными на 04.11.2026
         python seed.py 2026-12-01 — то же, с другой опорной датой

Заявки создаются и обрабатываются через функции модуля services, поэтому
номера, плановые даты, история статусов и журнал аудита формируются теми же
алгоритмами, что и при работе пользователей. Генератор детерминирован.
"""
import random
import sys
from datetime import date, datetime, time, timedelta

from flask import current_app

from app import create_app, init_classifiers
from app.models import (ROLE_ADMIN, ROLE_STAFF, ROLE_STUDENT, CertType, Role,
                        Student, User, db)
from app.services import change_status, create_request, dative_name, save_vyzov
from app.workdays import add_workdays, is_workday

PASSWORDS = {ROLE_ADMIN: "admin2026", ROLE_STAFF: "operator2026",
             ROLE_STUDENT: "student2026"}

CERT_TYPES = [
    # код, наименование, срок (раб. дн.), макс. экз., шаблон АИС, активна, описание
    ("OB", "Справка об обучении", 2, 5, True, True,
     "Подтверждает факт обучения; предоставляется по месту требования"),
    ("RAB", "Справка об обучении для предоставления по месту работы", 2, 3,
     True, True, "Для работодателя студента или родителя"),
    ("VK", "Справка для военного комиссариата", 3, 2, True, True,
     "Для постановки на воинский учёт и отсрочки от призыва"),
    ("SZ", "Справка для органов социальной защиты населения", 3, 3, True,
     True, "Для назначения пособий и субсидий"),
    ("SFR", "Справка для Социального фонда России", 3, 2, True, True,
     "Для назначения или продления пенсии по случаю потери кормильца"),
    ("STIP", "Справка о размере стипендии и иных выплат", 3, 2, True, True,
     "Для обучающихся, которым назначены стипендия или иные выплаты"),
    ("VYZ", "Справка-вызов", 5, 2, True, True,
     "Для учебного отпуска (ст. 173 ТК РФ); форма — приказ Минобрнауки России "
     "№ 1368; заочная и очно-заочная формы; выдаётся на бумаге"),
    ("AKD", "Академическая справка", 10, 1, False, True,
     "Для перевода в другую образовательную организацию или восстановления; "
     "оформляется на бланке установленного образца"),
    ("ARH", "Справка о периоде обучения (для отчисленных)", 10, 1, False,
     False, "Через АИС не заказывается: оформляется по письменному заявлению"),
]

STAFF = [("admin", "Соколов Андрей Петрович", ROLE_ADMIN, "admin@ais.local"),
         ("operator", "Белова Ольга Викторовна", ROLE_STAFF, "belova@ais.local"),
         ("operator2", "Кравцова Наталья Игоревна", ROLE_STAFF,
          "kravtsova@ais.local")]

FIT = "Факультет информационных технологий"
FEC = "Факультет экономики и управления"
GROUPS = {
    "ИСТ-231": (FIT, "09.03.02 Информационные системы и технологии", 2, "OCH", 2023),
    "ИСТ-221з": (FIT, "09.03.02 Информационные системы и технологии", 3, "ZAO", 2022),
    "ПИ-241": (FIT, "09.03.03 Прикладная информатика", 1, "OCH", 2024),
    "ПИ-211оз": (FIT, "09.03.03 Прикладная информатика", 4, "OZ", 2021),
    "БИ-221": (FEC, "38.03.05 Бизнес-информатика", 3, "OCH", 2022),
    "ЭК-231з": (FEC, "38.03.01 Экономика", 2, "ZAO", 2023),
}

# Основа обучения у всех — договор: по мониторингу 2021 г. 100 % студентов
# университета обучаются по договорам об оказании платных услуг (табл. 1.1 ВКР).
# Последний элемент — назначена ли стипендия или иные выплаты (для справки STIP).
STUDENTS = [
    ("student", "Иванова Мария Сергеевна", "ИСТ-231", "F", "PAY"),
    ("petrov", "Петров Дмитрий Алексеевич", "ИСТ-231", "M", "PAY"),
    ("smirnova", "Смирнова Анна Олеговна", "ИСТ-231", "F", "-"),
    ("kuznetsov", "Кузнецов Илья Романович", "ИСТ-231", "M", "-"),
    ("orlova", "Орлова Екатерина Денисовна", "ИСТ-221з", "F", "-"),
    ("vasiliev", "Васильев Артём Николаевич", "ИСТ-221з", "M", "-"),
    ("fedorova", "Фёдорова Полина Андреевна", "ИСТ-221з", "F", "-"),
    ("morozov", "Морозов Кирилл Евгеньевич", "ПИ-241", "M", "PAY"),
    ("volkova", "Волкова Дарья Максимовна", "ПИ-241", "F", "PAY"),
    ("lebedev", "Лебедев Никита Сергеевич", "ПИ-241", "M", "-"),
    ("kozlova", "Козлова Алина Витальевна", "ПИ-241", "F", "-"),
    ("novikov", "Новиков Егор Павлович", "ПИ-211оз", "M", "-"),
    ("zaitseva", "Зайцева Виктория Игоревна", "ПИ-211оз", "F", "-"),
    ("pavlov", "Павлов Максим Олегович", "ПИ-211оз", "M", "-"),
    ("semenova", "Семёнова Ксения Артёмовна", "БИ-221", "F", "PAY"),
    ("golubev", "Голубев Тимур Ринатович", "БИ-221", "M", "PAY"),
    ("vinogradova", "Виноградова София Михайловна", "БИ-221", "F", "-"),
    ("bogdanov", "Богданов Глеб Константинович", "БИ-221", "M", "-"),
    ("vorobieva", "Воробьёва Милана Руслановна", "ЭК-231з", "F", "-"),
    ("frolov", "Фролов Ярослав Дмитриевич", "ЭК-231з", "M", "-"),
    ("alekseeva", "Алексеева Варвара Юрьевна", "ЭК-231з", "F", "-"),
    ("yakovlev", "Яковлев Матвей Ильич", "ИСТ-231", "M", "PAY"),
]

PURPOSES = {
    "OB": ["по месту требования", "в управляющую компанию по месту жительства",
           "в визовый центр для оформления визы", "в МФЦ по месту жительства",
           "в банк для оформления кредитной карты"],
    "RAB": ["по месту работы студента", "по месту работы родителя",
            "по месту работы для оформления гибкого графика"],
    "VK": ["в военный комиссариат по месту воинского учёта"],
    "SZ": ["в управление социальной защиты населения по месту жительства",
           "в МФЦ для назначения ежемесячного пособия"],
    "SFR": ["в клиентскую службу Социального фонда России по месту жительства"],
    "STIP": ["в органы социальной защиты для расчёта субсидии",
             "в МФЦ для подтверждения дохода семьи"],
    "VYZ": ["по месту работы для оформления учебного отпуска на сессию"],
    "AKD": ["для перевода в другую образовательную организацию",
            "для предоставления по месту требования"],
}
WEIGHTS = {"OB": 34, "RAB": 14, "VK": 12, "SZ": 9, "SFR": 6, "STIP": 7,
           "VYZ": 12, "AKD": 3}
# выдаются только на бумаге с подписью и печатью (не PDF в кабинете)
PAPER_ONLY = {"VYZ"}
# каналы поступления: ЕЛК — для справок из его онлайн-каталога (справка об
# обучении, справка для военкомата); остальное — АИС, МФСО, куратор
ELK_TYPES = {"OB", "RAB", "VK"}
CHANNEL_WEIGHTS = {True: {"AIS": 40, "ELK": 35, "MFSO": 13, "KUR": 12},
                   False: {"AIS": 60, "MFSO": 22, "KUR": 18}}
# период сессии для справки-вызова (демо: зимняя сессия заочников)
VYZ_PERIOD = (date(2027, 1, 12), date(2027, 1, 31))

REJECTS = {
    "VYZ": "Справка-вызов оформляется только обучающимся заочной и "
           "очно-заочной форм обучения",
    "STIP": "Обучающемуся не назначены стипендия или иные выплаты",
    "*": "Не указана организация, в которую предоставляется справка; "
         "подайте заявку повторно с уточнением",
}


def at(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute))


def work_moment(rnd, day, lo=9, hi=17):
    """Случайный момент рабочего времени в заданный день."""
    return at(day, rnd.randint(lo, hi - 1), rnd.randint(0, 59))


def build_users():
    roles = {r.code: r for r in Role.query.all()}
    staff = {}
    for login, name, role, mail in STAFF:
        u = User(login=login, full_name=name, role=roles[role], email=mail,
                 created_at=datetime(2026, 8, 25, 10, 0))
        u.set_password(PASSWORDS[role])
        db.session.add(u)
        staff[login] = u
    rnd = random.Random(7)
    students = []
    for i, (login, name, group, _sex, pay) in enumerate(STUDENTS, 1):
        faculty, direction, course, form, year = GROUPS[group]
        u = User(login=login, full_name=name, role=roles[ROLE_STUDENT],
                 email=f"{login}@student.ais.local",
                 created_at=datetime(2026, 8, 28, 12, 0))
        u.set_password(PASSWORDS[ROLE_STUDENT])
        years = 5 if form != "OCH" else 4
        st = Student(
            user=u, record_book_no=f"{year % 100:02d}{i:04d}{rnd.randint(10, 99)}",
            birth_date=date(2026 - course - 17 - rnd.randint(0, 2),
                            rnd.randint(1, 12), rnd.randint(1, 28)),
            faculty=faculty, direction=direction, group_code=group,
            course=course, study_form=form, funding="DOG",
            enroll_order=f"{rnd.randint(1100, 1999)}-с",
            enroll_date=date(year, 8, rnd.randint(20, 31)),
            graduation_date=date(year + years, 6, 30))
        db.session.add(st)
        st.pay = pay == "PAY"  # атрибут только для моделирования, в БД не хранится
        students.append(st)
    db.session.flush()
    return staff, students


def pick_delivery(rnd, ctype):
    roll = rnd.random()
    if ctype.printable and ctype.electronic and roll < 0.45:
        return "EL", None
    if roll < 0.9:
        return "DEAN", None
    return "POST", f"{rnd.randint(101000, 129999)}, г. Москва, ул. Профсоюзная, " \
                   f"д. {rnd.randint(1, 140)}, кв. {rnd.randint(1, 300)}"


def simulate(anchor):
    """Заявки за период 01.09 — опорная дата с правдоподобной обработкой."""
    rnd = random.Random(2026)
    hol = current_app.config["HOLIDAYS"]
    staff, students = build_users()
    types = {t.code: t for t in CertType.query.all()}
    operators = [staff["operator"], staff["operator2"]]
    codes = list(WEIGHTS)
    weights = [WEIGHTS[c] for c in codes]

    # моменты подачи: в среднем ~2,5 заявки в рабочий день, иногда вечером
    moments = []
    day = date(2026, 9, 1)
    while day < anchor:
        n = rnd.choice([1, 2, 2, 3, 3, 4]) if is_workday(day, hol) else \
            rnd.choice([0, 0, 1])
        if day.month == 9 and day.day < 20:
            n += 1  # сентябрьский пик: справки в военкомат, соцзащиту
        for _ in range(n):
            moments.append(work_moment(rnd, day, 8, 22))
        day += timedelta(days=1)
    moments.sort()
    now_limit = at(anchor, 8, 30)

    for created in moments:
        code = rnd.choices(codes, weights)[0]
        st = rnd.choice(students)
        # справку-вызов и о стипендии в основном заказывают «правильные»
        # студенты; часть ошибочных заявок оставлена для отклонения
        if code == "VYZ" and st.study_form == "OCH" and rnd.random() < 0.85:
            st = rnd.choice([s for s in students if s.study_form != "OCH"])
        if code == "STIP" and not st.pay and rnd.random() < 0.85:
            st = rnd.choice([s for s in students if s.pay])
        ctype = types[code]
        delivery, addr = pick_delivery(rnd, ctype)
        op = rnd.choice(operators)
        weights_ch = CHANNEL_WEIGHTS[code in ELK_TYPES]
        channel = rnd.choices(list(weights_ch), list(weights_ch.values()))[0]
        ext = str(rnd.randint(100000, 999999)) if channel == "ELK" else None
        if channel != "AIS":  # принята другим каналом — регистрирует сотрудник
            created = max(created, work_moment(rnd, created.date())) \
                if is_workday(created.date(), hol) else created
        req = create_request(st, ctype.id, rnd.choice(PURPOSES[code]),
                             rnd.randint(1, min(2, ctype.max_copies)),
                             delivery, addr, None,
                             author=st.user if channel == "AIS" else op,
                             now=created, channel=channel, ext_number=ext)
        # отмена студентом в течение часа
        if rnd.random() < 0.04:
            change_status(req, "CANC", st.user, "Отменена студентом",
                          now=created + timedelta(minutes=rnd.randint(5, 50)))
            continue
        take = work_moment(rnd, add_workdays(created.date(), rnd.choice([0, 1, 1]),
                                             hol))
        take = max(take, created + timedelta(minutes=20))
        # часть заявок последних дней ещё не взята в работу
        if take > now_limit or (created.date() >= anchor - timedelta(days=5)
                                and rnd.random() < 0.5):
            continue  # ещё «Новая»
        wrong_form = (code == "VYZ" and st.study_form == "OCH") or \
                     (code == "STIP" and not st.pay)
        if wrong_form or rnd.random() < 0.03:
            reason = REJECTS.get(code) if wrong_form else REJECTS["*"]
            change_status(req, "REJ", op, reason, now=take)
            continue
        change_status(req, "PREP", op, "Принята в работу", now=take)
        # готовность: обычно к плановой дате, иногда с опозданием
        delay = rnd.choices([-1, 0, 0, 0, 1, 2], [3, 6, 6, 6, 2, 1])[0]
        ready_day = add_workdays(req.planned_date, max(delay, 0), hol)
        if delay < 0:
            ready_day = max(take.date(), req.planned_date - timedelta(days=1))
            if not is_workday(ready_day, hol):
                ready_day = req.planned_date
        ready = max(work_moment(rnd, ready_day, 10, 17),
                    take + timedelta(hours=1))
        # несколько незакрытых просроченных заявок для контроля сроков
        if ready > now_limit or (req.planned_date < anchor - timedelta(days=1)
                                 and req.planned_date > anchor - timedelta(days=9)
                                 and rnd.random() < 0.25):
            continue
        if req.is_vyzov:
            save_vyzov(req, op, dative_name(st.user.full_name), "PA",
                       *VYZ_PERIOD, now=take)
        change_status(req, "READY", op, "Справка подготовлена и подписана",
                      now=ready)
        issue_day = add_workdays(ready.date(), rnd.choice([0, 1, 1, 2, 3, 5]), hol)
        issued = work_moment(rnd, issue_day, 10, 18)
        if issued > now_limit or rnd.random() < 0.05:
            continue
        note = {"EL": "Направлена в личный кабинет (PDF)",
                "DEAN": "Выдана лично под подпись",
                "POST": "Отправлена заказным письмом"}[delivery]
        change_status(req, "ISSUED", op, note, now=max(issued, ready))


def main(anchor):
    app = create_app()
    with app.app_context():
        db.drop_all()
        init_classifiers()
        for i, (code, name, days, mx, printable, active, descr) in \
                enumerate(CERT_TYPES):
            db.session.add(CertType(code=code, name=name, lead_days=days,
                                    max_copies=mx, printable=printable,
                                    electronic=code not in PAPER_ONLY,
                                    is_active=active, description=descr,
                                    sort_order=(i + 1) * 10))
        db.session.flush()
        simulate(anchor)
        db.session.commit()
        from app.models import Request
        print(f"Пользователей: {User.query.count()}, "
              f"студентов: {Student.query.count()}, "
              f"заявок: {Request.query.count()}")
        print("Учётные записи: admin/admin2026, operator/operator2026, "
              "student/student2026")


if __name__ == "__main__":
    main(date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1
         else date(2026, 11, 4))
