"""Таблицы сервера."""
from app.models.client import Client, Car, Device, LoginCode
from app.models.shop import (Appointment, BookingDay, StoredSet, Visit,
                             VisitItem, SalaryAccrual, ShopEmployee,
                             ShopShift, QueueSnapshot, ShopSetting,
                             PENDING, TAKEN, REJECTED)

__all__ = [
    'Client', 'Car', 'Device', 'LoginCode',
    'Appointment', 'BookingDay', 'StoredSet', 'Visit', 'VisitItem',
    'SalaryAccrual', 'ShopEmployee', 'ShopShift', 'QueueSnapshot',
    'ShopSetting', 'PENDING', 'TAKEN', 'REJECTED',
]
