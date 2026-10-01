"""Таблицы сервера."""
from app.models.account import Account, AccountPayment, Shop
from app.models.client import Client, Car, Device, LoginCode
from app.models.notice import (Notice, TITLES, KIND_BOOKED, KIND_REMINDER,
                               KIND_CANCELLED, KIND_MOVED, KIND_STORAGE,
                               KIND_SEASON, ABOUT_AUTUMN, ABOUT_SPRING,
                               WAITING, SENT, FAILED, SKIPPED,
                               BY_TELEGRAM, BY_PUSH)
from app.models.push import PushSubscription
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
    'Account', 'AccountPayment', 'Shop',
    'Client', 'Car', 'Device', 'LoginCode',
    'Notice', 'TITLES', 'BY_TELEGRAM', 'BY_PUSH', 'KIND_BOOKED', 'KIND_REMINDER', 'KIND_CANCELLED', 'KIND_MOVED',
    'KIND_STORAGE', 'KIND_SEASON', 'ABOUT_AUTUMN', 'ABOUT_SPRING',
    'WAITING', 'SENT', 'FAILED', 'SKIPPED',
    'PushSubscription',
    'Appointment', 'BookingDay', 'StoredSet', 'Visit', 'VisitItem',
    'SalaryAccrual', 'SalaryPayout', 'ShopEmployee', 'ShopShift',
    'QueueSnapshot',
    'ShopSetting', 'PENDING', 'TAKEN', 'REJECTED',
    'StaffUser', 'StaffAction', 'ROLE_OWNER', 'ROLE_ADMIN', 'ROLE_TITLES',
    'ROLE_PERMISSIONS', 'ALL_PERMISSIONS', 'PERMISSION_TITLES',
    'PERM_REVENUE', 'PERM_ORDERS', 'PERM_SALARY_ALL', 'PERM_SALARY_PAY',
    'PERM_BOOKING', 'PERM_STORAGE', 'PERM_CLIENTS', 'PERM_STAFF',
]
