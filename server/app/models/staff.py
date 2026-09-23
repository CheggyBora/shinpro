"""
Кто смотрит дашборд: владелец, управляющий, мастер, приёмщик.

Учётные записи живут здесь, а не в базе цеха, и это сознательно.
Уволенный мастер должен терять доступ в ту же минуту, а не через
десять — до следующего обмена. Права — дело сервера, и решаются они
на сервере.

Вход тот же, что у клиента: телефон, код на первом заходе, дальше ПИН.
Заводить персоналу отдельный способ входа незачем — человек и так его
знает, если хоть раз обслуживался.
"""
from datetime import datetime

from sqlalchemy import (Column, Integer, String, Boolean, DateTime, Text,
                        ForeignKey)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now as shop_now

# --- Роли -------------------------------------------------------------
# Роль — это заготовка прав, а не жёсткая рамка: любую галочку у
# конкретного человека можно снять или добавить отдельно.
ROLE_OWNER = 'owner'
ROLE_MANAGER = 'manager'
ROLE_MASTER = 'master'
ROLE_RECEPTIONIST = 'receptionist'

ROLE_TITLES = {
    ROLE_OWNER: 'Владелец',
    ROLE_MANAGER: 'Управляющий',
    ROLE_MASTER: 'Мастер',
    ROLE_RECEPTIONIST: 'Приёмщик',
}

# --- Права ------------------------------------------------------------
# Каждое право — про один вопрос: «что этот человек видит на экране».
PERM_REVENUE = 'revenue'            # выручка, средний чек, отчёты
PERM_ORDERS = 'orders'              # наряды всех мастеров
PERM_SALARY_ALL = 'salary_all'      # зарплаты всех
PERM_SALARY_OWN = 'salary_own'      # только своя зарплата и свои наряды
PERM_BOOKING = 'booking'            # записи на обслуживание
PERM_STORAGE = 'storage'            # хранение шин и заявки клиентов
PERM_CLIENTS = 'clients'            # клиенты и их история
PERM_STAFF = 'staff'                # заводить людей и раздавать права

ALL_PERMISSIONS = (PERM_REVENUE, PERM_ORDERS, PERM_SALARY_ALL, PERM_SALARY_OWN,
                   PERM_BOOKING, PERM_STORAGE, PERM_CLIENTS, PERM_STAFF)

PERMISSION_TITLES = {
    PERM_REVENUE: 'Выручка и отчёты',
    PERM_ORDERS: 'Наряды всех мастеров',
    PERM_SALARY_ALL: 'Зарплаты всех сотрудников',
    PERM_SALARY_OWN: 'Своя зарплата и свои наряды',
    PERM_BOOKING: 'Записи на обслуживание',
    PERM_STORAGE: 'Хранение шин',
    PERM_CLIENTS: 'Клиенты и история',
    PERM_STAFF: 'Сотрудники и права',
}

ROLE_PERMISSIONS = {
    ROLE_OWNER: list(ALL_PERMISSIONS),
    # Управляющему зарплаты по умолчанию не открываем: это решение
    # владельца, а не наше. Галочку он поставит сам, если считает нужным
    ROLE_MANAGER: [PERM_REVENUE, PERM_ORDERS, PERM_BOOKING, PERM_STORAGE,
                   PERM_CLIENTS],
    ROLE_MASTER: [PERM_SALARY_OWN],
    ROLE_RECEPTIONIST: [PERM_BOOKING, PERM_STORAGE, PERM_CLIENTS],
}


class StaffUser(Base):
    """
    Человек, имеющий доступ к дашборду.

    Телефон — и логин, и способ найти его в базе цеха. Номер сотрудника
    (employee_shop_id) нужен мастеру: по нему ищутся его наряды и его
    начисления. Без номера мастер не увидит ничего своего — поэтому
    владелец указывает его при заведении.
    """
    __tablename__ = 'staff_users'

    id = Column(Integer, primary_key=True, autoincrement=True)

    phone = Column(String(20), nullable=False, unique=True, index=True)
    name = Column(String(200), nullable=True)
    role = Column(String(20), default=ROLE_MANAGER, nullable=False)

    # Права через запятую. Пусто — значит берём права роли: у большинства
    # людей они не отличаются, и хранить копию списка незачем
    permissions = Column(Text, nullable=True)

    employee_shop_id = Column(Integer, nullable=True, index=True)

    pin_hash = Column(String(255), nullable=True)
    pin_updated_at = Column(DateTime, nullable=True)
    pin_failures = Column(Integer, default=0, nullable=False)
    pin_blocked_at = Column(DateTime, nullable=True)
    phone_verified_at = Column(DateTime, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)

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


class StaffAction(Base):
    """
    Журнал: кто, когда и что смотрел или менял.

    Дашборд показывает выручку и зарплаты всего шиномонтажа. Кто в него
    заходил — такой же важный факт, как сами цифры.
    """
    __tablename__ = 'staff_actions'

    id = Column(Integer, primary_key=True, autoincrement=True)

    staff_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True,
                      index=True)
    happened_at = Column(DateTime, default=shop_now, nullable=False,
                         index=True)

    action = Column(String(50), nullable=False)
    detail = Column(Text, nullable=True)
    # Телефон храним строкой отдельно: запись в журнале должна пережить
    # удаление учётки, иначе след потеряется вместе с человеком
    phone = Column(String(20), nullable=True)
