"""
Кто смотрит дашборд: владелец и админ.

Учётные записи живут здесь, а не в базе цеха, и это сознательно.
Человек, которому закрыли доступ, должен потерять его в ту же минуту,
а не через десять — до следующего обмена. Права — дело сервера, и
решаются они на сервере.

Вход тот же, что у клиента: телефон, код на первом заходе, дальше ПИН.
Заводить персоналу отдельный способ входа незачем — человек и так его
знает, если хоть раз обслуживался.
"""
from datetime import datetime

from sqlalchemy import (Column, Integer, String, Boolean, DateTime, Text,
                        ForeignKey, UniqueConstraint)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now as shop_now

# --- Роли -------------------------------------------------------------
# Дашборд смотрят двое: владелец и админ. Мастера сюда не заходят —
# свою зарплату они видят в программе цеха, у приёмщика на экране.
#
# Роль — заготовка прав, а не жёсткая рамка: любую галочку у
# конкретного человека можно снять или добавить отдельно.
ROLE_OWNER = 'owner'
ROLE_ADMIN = 'admin'

ROLE_TITLES = {
    ROLE_OWNER: 'Владелец',
    ROLE_ADMIN: 'Админ',
}

# --- Права ------------------------------------------------------------
# Каждое право — про один вопрос: «что этот человек видит на экране».
PERM_REVENUE = 'revenue'            # выручка, средний чек, отчёты
PERM_ORDERS = 'orders'              # наряды
PERM_SALARY_ALL = 'salary_all'      # зарплаты и начисления за смену
PERM_SALARY_PAY = 'salary_pay'      # выдать зарплату переводом на карту
PERM_BOOKING = 'booking'            # записи на обслуживание
PERM_STORAGE = 'storage'            # хранение шин и заявки клиентов
PERM_CLIENTS = 'clients'            # клиенты и их история
PERM_STAFF = 'staff'                # заводить людей и раздавать права
# Раньше календарь и склад видел всякий, кто вошёл, а касса шла вместе
# с выручкой. Теперь у каждого своя галочка (решение владельца 29.10.2026)
PERM_CALENDAR = 'calendar'          # календарь: задачи и комментарии
PERM_STOCK = 'stock'                # склад: остатки
PERM_CASH = 'cash'                  # касса: ордера и остаток наличных

ALL_PERMISSIONS = (PERM_REVENUE, PERM_CASH, PERM_ORDERS, PERM_SALARY_ALL,
                   PERM_SALARY_PAY, PERM_BOOKING, PERM_CALENDAR, PERM_STOCK,
                   PERM_STORAGE, PERM_CLIENTS, PERM_STAFF)

# Отчёты в Telegram, которые можно отметить человеку в «Доступе», и
# право, без которого отчёт ему не уйдёт: сводка по смене — это деньги
REPORT_SHIFT, REPORT_TASK, REPORT_DIGEST = 'shift', 'task', 'digest'
REPORT_STORAGE, REPORT_PAINT = 'storage', 'paint'
REPORTS = (
    (REPORT_SHIFT, 'Сводка по смене', PERM_REVENUE),
    (REPORT_TASK, 'Новые задачи из календаря', PERM_CALENDAR),
    (REPORT_DIGEST, 'Задачи утром и вечером', PERM_CALENDAR),
    (REPORT_STORAGE, 'Склад: отвезти и привезти комплекты', PERM_STORAGE),
    (REPORT_PAINT, 'Покраска дисков', PERM_CALENDAR),
)
REPORT_KINDS = tuple(key for key, _title, _perm in REPORTS)
REPORT_PERMISSION = {key: perm for key, _title, perm in REPORTS}

PERMISSION_TITLES = {
    PERM_REVENUE: 'Выручка и отчёты',
    PERM_ORDERS: 'Наряды',
    PERM_SALARY_ALL: 'Зарплаты сотрудников',
    PERM_SALARY_PAY: 'Выдача зарплаты на карту',
    PERM_BOOKING: 'Записи на обслуживание',
    PERM_STORAGE: 'Хранение шин',
    PERM_CLIENTS: 'Клиенты и история',
    PERM_STAFF: 'Сотрудники и права',
    PERM_CALENDAR: 'Календарь и задачи',
    PERM_STOCK: 'Склад',
    PERM_CASH: 'Касса',
}

ROLE_PERMISSIONS = {
    ROLE_OWNER: list(ALL_PERMISSIONS),
    # Админу открыто всё, кроме раздачи доступа и выдачи денег: заводить
    # людей и платить зарплату — дело владельца. Любую галочку владелец
    # может добавить или снять отдельно
    ROLE_ADMIN: [PERM_REVENUE, PERM_CASH, PERM_ORDERS, PERM_SALARY_ALL,
                 PERM_BOOKING, PERM_CALENDAR, PERM_STOCK, PERM_STORAGE,
                 PERM_CLIENTS],
}


class StaffUser(Base):
    """
    Человек, имеющий доступ к дашборду: владелец или админ.

    Телефон — и логин, и способ узнать человека: тем же номером он
    записан в базе цеха, если когда-нибудь обслуживался.
    """
    __tablename__ = 'staff_users'

    id = Column(Integer, primary_key=True, autoincrement=True)

    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=True,
                        index=True)

    # Телефон уникален внутри аккаунта: один и тот же человек может
    # вести учёт в двух не связанных между собой шиномонтажах
    phone = Column(String(20), nullable=False, index=True)
    name = Column(String(200), nullable=True)
    role = Column(String(20), default=ROLE_ADMIN, nullable=False)

    # Права через запятую. Пусто — значит берём права роли: у большинства
    # людей они не отличаются, и хранить копию списка незачем
    permissions = Column(Text, nullable=True)

    pin_hash = Column(String(255), nullable=True)
    pin_updated_at = Column(DateTime, nullable=True)
    pin_failures = Column(Integer, default=0, nullable=False)
    pin_blocked_at = Column(DateTime, nullable=True)
    phone_verified_at = Column(DateTime, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)

    # Владелец сервера — тот, кто видит «Заказчиков». Раньше его узнавали
    # по номеру из настроек сервера, и сменить номер было нельзя
    is_platform_owner = Column(Boolean, default=False, nullable=False,
                               server_default='0')

    # Telegram человека (ник без «@») и какие отчёты ему слать:
    # «shift,task» — через запятую (решение владельца 29.10.2026)
    telegram = Column(String(64), nullable=True)
    reports = Column(Text, nullable=True)

    # Кто завёл и когда: без этого в журнале не разобрать, откуда
    # у человека взялся доступ
    created_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    created_at = Column(DateTime, default=shop_now, nullable=False)
    last_seen_at = Column(DateTime, nullable=True)

    # Пересоздание доступа: после смены роли или отключения старые токены
    # должны перестать работать сразу, а не доживать свои тридцать дней
    access_changed_at = Column(DateTime, default=shop_now, nullable=False)

    created_by = relationship('StaffUser', remote_side=[id])

    @property
    def role_title(self):
        return ROLE_TITLES.get(self.role, self.role)

    @property
    def title(self):
        return self.name or self.phone

    def allowed(self):
        """Права этого человека: свои, если заданы, иначе права роли."""
        if self.permissions:
            saved = [item.strip() for item in self.permissions.split(',')
                     if item.strip()]
            return [item for item in saved if item in ALL_PERMISSIONS]
        return list(ROLE_PERMISSIONS.get(self.role, []))

    def can(self, permission):
        if not self.is_active:
            return False
        return permission in self.allowed()

    def report_kinds(self):
        """Отмеченные отчёты — все, даже те, на которые сейчас нет права."""
        return [item.strip() for item in (self.reports or '').split(',')
                if item.strip() in REPORT_KINDS]

    def gets_report(self, kind):
        """Уйдёт ли ему отчёт: отмечен, есть ник и есть право на то, что в отчёте."""
        return (self.is_active and bool(self.telegram) and kind in self.report_kinds()
                and self.can(REPORT_PERMISSION.get(kind, PERM_STAFF)))


UniqueConstraint(StaffUser.account_id, StaffUser.phone,
                 name='uq_staff_users_account_phone')


class StaffAction(Base):
    """
    Журнал: кто, когда и что смотрел или менял.

    Дашборд показывает выручку и зарплаты всего шиномонтажа. Кто в него
    заходил — такой же важный факт, как сами цифры.
    """
    __tablename__ = 'staff_actions'

    id = Column(Integer, primary_key=True, autoincrement=True)

    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=True,
                        index=True)
    staff_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True,
                      index=True)
    happened_at = Column(DateTime, default=shop_now, nullable=False,
                         index=True)

    action = Column(String(50), nullable=False)
    detail = Column(Text, nullable=True)
    # Телефон храним строкой отдельно: запись в журнале должна пережить
    # удаление учётки, иначе след потеряется вместе с человеком
    phone = Column(String(20), nullable=True)
