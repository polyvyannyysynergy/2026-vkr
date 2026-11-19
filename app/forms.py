"""Формы ввода (Flask-WTF): валидация данных и CSRF-токен."""
from flask_wtf import FlaskForm
from wtforms import (BooleanField, DateField, HiddenField, IntegerField,
                     PasswordField, SelectField, StringField, TextAreaField)
from wtforms.validators import (DataRequired, EqualTo, Length,
                                NumberRange, Optional, Regexp, ValidationError)

from .models import CHANNELS, DELIVERY, FUNDING, STUDY_FORMS, VYZ_BASIS


class LoginForm(FlaskForm):
    login = StringField("Логин", validators=[DataRequired(), Length(max=40)])
    password = PasswordField("Пароль", validators=[DataRequired()])


class PasswordForm(FlaskForm):
    old = PasswordField("Текущий пароль", validators=[DataRequired()])
    new = PasswordField("Новый пароль", validators=[
        DataRequired(), Length(min=8, message="Не менее 8 символов"),
        Regexp(r"^(?=.*\d)(?=.*[A-Za-zА-Яа-я]).+$",
               message="Буквы и цифры обязательны")])
    repeat = PasswordField("Повтор", validators=[
        EqualTo("new", message="Пароли не совпадают")])


class RequestForm(FlaskForm):
    cert_type = SelectField("Тип справки", coerce=int,
                            validators=[DataRequired()])
    purpose = StringField("Место предоставления (цель)", validators=[
        DataRequired(), Length(min=3, max=200)])
    copies = IntegerField("Количество экземпляров", default=1,
                          validators=[DataRequired(), NumberRange(1, 10)])
    delivery = SelectField("Способ получения", choices=list(DELIVERY.items()))
    post_address = StringField("Почтовый адрес (для отправки почтой)",
                               validators=[Optional(), Length(max=250)])
    comment = TextAreaField("Комментарий для деканата",
                            validators=[Optional(), Length(max=400)])


class RegisterForm(RequestForm):
    """Регистрация сотрудником заявки, принятой через ЕЛК, МФСО или куратора."""
    record_book_no = StringField("№ зачётной книжки студента", validators=[
        DataRequired(), Length(max=20)])
    channel = SelectField("Канал поступления", choices=[
        (k, v) for k, v in CHANNELS.items() if k != "AIS"])
    ext_number = StringField("№ заявки в канале (если есть)",
                             validators=[Optional(), Length(max=30)])
    comment = TextAreaField("Комментарий",
                            validators=[Optional(), Length(max=400)])


class AppealForm(FlaskForm):
    """Текст обращения (письмо, сообщение куратора, запись МФСО) для разбора
    локальной языковой моделью; не сохраняется."""
    text = TextAreaField("Текст обращения", validators=[
        DataRequired(), Length(min=10, max=3000)])


class VyzovForm(FlaskForm):
    """Реквизиты справки-вызова (приказ Минобрнауки России № 1368)."""
    name_dat = StringField("ФИО студента в дательном падеже", validators=[
        DataRequired(), Length(min=5, max=120)])
    basis = SelectField("Основание (для чего предоставляются гарантии)",
                        choices=list(VYZ_BASIS.items()))
    period_from = DateField("Период с", validators=[DataRequired()])
    period_to = DateField("по", validators=[DataRequired()])

    def validate_period_to(self, field):
        if self.period_from.data and field.data and \
                field.data < self.period_from.data:
            raise ValidationError("Дата окончания раньше даты начала")


class StatusForm(FlaskForm):
    to_status = SelectField("Новый статус", validators=[DataRequired()])
    # статус, который сотрудник видел на странице: если его успел сменить
    # другой сотрудник, переход не выполняется
    seen_status = HiddenField()
    comment = TextAreaField("Комментарий / причина отклонения",
                            validators=[Optional(), Length(max=400)])


class CertTypeForm(FlaskForm):
    code = StringField("Код", validators=[
        DataRequired(), Length(max=10),
        Regexp(r"^[A-Z0-9-]+$", message="Латинские прописные, цифры, дефис")])
    name = StringField("Наименование", validators=[DataRequired(),
                                                   Length(max=160)])
    lead_days = IntegerField("Срок изготовления, раб. дней",
                             validators=[NumberRange(0, 30)])
    max_copies = IntegerField("Макс. экземпляров",
                              validators=[NumberRange(1, 10)])
    sort_order = IntegerField("Порядок", default=100,
                              validators=[NumberRange(0, 999)])
    printable = BooleanField("Формируется по шаблону АИС (печать/PDF)")
    electronic = BooleanField("Может выдаваться электронно (PDF в кабинете)",
                              default=True)
    is_active = BooleanField("Доступна для заказа", default=True)
    description = TextAreaField("Описание", validators=[Optional(),
                                                        Length(max=400)])


class UserForm(FlaskForm):
    login = StringField("Логин", validators=[
        DataRequired(), Length(min=3, max=40),
        Regexp(r"^[a-z0-9._-]+$", message="Строчные латинские, цифры, . _ -")])
    full_name = StringField("ФИО", validators=[DataRequired(), Length(max=120)])
    email = StringField("E-mail", validators=[
        Optional(), Length(max=120),
        Regexp(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", message="Неверный e-mail")])
    role = SelectField("Роль", validators=[DataRequired()])
    password = PasswordField("Начальный пароль", validators=[
        DataRequired(), Length(min=8)])
    # поля карточки студента (обязательны для роли «Студент»)
    record_book_no = StringField("№ зачётной книжки",
                                 validators=[Optional(), Length(max=20)])
    birth_date = DateField("Дата рождения", validators=[Optional()])
    faculty = StringField("Факультет", validators=[Optional(), Length(max=120)])
    direction = StringField("Направление подготовки",
                            validators=[Optional(), Length(max=160)])
    group_code = StringField("Группа", validators=[Optional(), Length(max=20)])
    course = IntegerField("Курс", validators=[Optional(), NumberRange(1, 6)])
    study_form = SelectField("Форма обучения", choices=list(STUDY_FORMS.items()))
    funding = SelectField("Основа обучения", choices=list(FUNDING.items()))
    enroll_order = StringField("Приказ о зачислении",
                               validators=[Optional(), Length(max=40)])
    enroll_date = DateField("Дата зачисления", validators=[Optional()])
    graduation_date = DateField("Дата окончания", validators=[Optional()])
