"""Таблицы сервера."""
from app.models.account import Account, AccountPayment, Shop, AccountDomain
from app.models.client import Client, Car, Device, LoginCode
from app.models.notice import (Notice, TITLES, KIND_BOOKED, KIND_REMINDER,
                               KIND_CANCELLED, KIND_MOVED, KIND_STORAGE,
                               KIND_SEASON, KIND_READY, KIND_QUEUE,
                               KIND_ARRIVE, KIND_LATE,
                               ABOUT_AUTUMN, ABOUT_SPRING,
                               WAITING, SENT, FAILED, SKIPPED,
                               BY_TELEGRAM, BY_PUSH)
from app.models.photo import MasterDevice, OpenOrder, OrderPhoto, Arrival
from app.models.push import PushSubscription
from app.models.live import LiveTicket
from app.models.task import (Task, Counterparty, CATEGORIES, CATEGORY_TITLES,
                             SOURCES)
from app.models.stock import StockItem
from app.models.cash import CashOrder
from app.models.links import ShopClient, ShopCar
from app.models.shop import (Appointment, BookingDay, StoredSet, Visit,
                             VisitItem, SalaryAccrual, SalaryPayout,
                             ShopEmployee, ShopShift, QueueSnapshot, ShopSetting,
                             PENDING, TAKEN, REJECTED)

from app.models.staff import (StaffUser, StaffAction, ROLE_OWNER, ROLE_ADMIN,
                              ROLE_TITLES, ROLE_PERMISSIONS, ALL_PERMISSIONS,
                              PERMISSION_TITLES, PERM_REVENUE, PERM_ORDERS,
                              PERM_SALARY_ALL, PERM_SALARY_PAY,
                              PERM_BOOKING, PERM_STORAGE, PERM_CLIENTS,
                              PERM_STAFF)

__all__ = [
    'Account', 'AccountPayment', 'Shop', 'AccountDomain',
    'Client', 'Car', 'Device', 'LoginCode',
    'Notice', 'TITLES', 'BY_TELEGRAM', 'BY_PUSH', 'KIND_BOOKED', 'KIND_REMINDER', 'KIND_CANCELLED', 'KIND_MOVED',
    'KIND_STORAGE', 'KIND_SEASON', 'KIND_READY', 'KIND_QUEUE', 'KIND_ARRIVE', 'KIND_LATE',
    'ABOUT_AUTUMN', 'ABOUT_SPRING',
    'WAITING', 'SENT', 'FAILED', 'SKIPPED',
    'MasterDevice', 'OpenOrder', 'OrderPhoto', 'Arrival',
    'PushSubscription', 'LiveTicket',
    'Task', 'Counterparty', 'CATEGORIES', 'CATEGORY_TITLES', 'SOURCES',
    'StockItem', 'CashOrder',
    'Appointment', 'BookingDay', 'StoredSet', 'Visit', 'VisitItem',
    'SalaryAccrual', 'SalaryPayout', 'ShopEmployee', 'ShopShift',
    'QueueSnapshot',
    'ShopSetting', 'PENDING', 'TAKEN', 'REJECTED',
    'StaffUser', 'StaffAction', 'ROLE_OWNER', 'ROLE_ADMIN', 'ROLE_TITLES',
    'ROLE_PERMISSIONS', 'ALL_PERMISSIONS', 'PERMISSION_TITLES',
    'PERM_REVENUE', 'PERM_ORDERS', 'PERM_SALARY_ALL', 'PERM_SALARY_PAY',
    'PERM_BOOKING', 'PERM_STORAGE', 'PERM_CLIENTS', 'PERM_STAFF',
]
