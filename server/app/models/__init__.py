"""Таблицы сервера."""
from app.models.client import Client, Car, Device, LoginCode
from app.models.shop import (Appointment, BookingDay, StoredSet, Visit,
                             VisitItem, SalaryAccrual, ShopEmployee,
                             ShopShift, QueueSnapshot, ShopSetting,
                             PENDING, TAKEN, REJECTED)

from app.models.staff import (StaffUser, StaffAction, ROLE_OWNER, ROLE_ADMIN,
                              ROLE_TITLES, ROLE_PERMISSIONS, ALL_PERMISSIONS,
                              PERMISSION_TITLES, PERM_REVENUE, PERM_ORDERS,
                              PERM_SALARY_ALL, PERM_BOOKING, PERM_STORAGE,
                              PERM_CLIENTS, PERM_STAFF)

__all__ = [
    'Client', 'Car', 'Device', 'LoginCode',
    'Appointment', 'BookingDay', 'StoredSet', 'Visit', 'VisitItem',
    'SalaryAccrual', 'ShopEmployee', 'ShopShift', 'QueueSnapshot',
    'ShopSetting', 'PENDING', 'TAKEN', 'REJECTED',
    'StaffUser', 'StaffAction', 'ROLE_OWNER', 'ROLE_ADMIN', 'ROLE_TITLES',
    'ROLE_PERMISSIONS', 'ALL_PERMISSIONS', 'PERMISSION_TITLES',
    'PERM_REVENUE', 'PERM_ORDERS', 'PERM_SALARY_ALL', 'PERM_BOOKING',
    'PERM_STORAGE', 'PERM_CLIENTS', 'PERM_STAFF',
]
