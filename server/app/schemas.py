"""
Что уходит в приложение и что от него приходит.

Отдельный слой от таблиц нужен по одной причине: клиенту нельзя
показывать всё, что лежит в базе. В записи есть внутренние поля обмена,
у клиента — признак блокировки; в приложении им делать нечего.
"""
from datetime import datetime, date
from typing import Optional, List

from pydantic import BaseModel, Field


# ----------------------------------------------------------------------
# Вход
# ----------------------------------------------------------------------

class StartIn(BaseModel):
    phone: str = Field(..., description='Номер телефона в любом написании')


class StartOut(BaseModel):
    # pin — спросить ПИН, verify — нужен код подтверждения
    step: str
    is_known: bool
    pin_is_blocked: bool = False
    # sms или email — каким каналом придёт код
    channel: str = 'sms'


class CodeRequestIn(BaseModel):
    phone: str
    email: Optional[str] = Field(
        None, description='Нужна, только если шиномонтаж шлёт коды письмом')


class CodeSentOut(BaseModel):
    sent: bool = True
    # Сколько код будет жить — по нему рисуется обратный отсчёт
    expires_in_seconds: int
    channel: str = 'sms'


class VerifyIn(BaseModel):
    phone: str
    code: str
    device_id: Optional[str] = None


class PinLoginIn(BaseModel):
    phone: str
    pin: str


class PinIn(BaseModel):
    pin: str


class TokenOut(BaseModel):
    token: str
    client_id: int
    name: Optional[str] = None
    phone: str
    # Пусто — значит человеку пора придумать ПИН
    pin_is_set: bool = False


class DeviceIn(BaseModel):
    device_id: str
    push_token: Optional[str] = None
    platform: Optional[str] = None
    app_version: Optional[str] = None


class ProfileIn(BaseModel):
    name: Optional[str] = None


# ----------------------------------------------------------------------
# Машины
# ----------------------------------------------------------------------

class CarOut(BaseModel):
    id: int
    license_plate: str
    wheels_assembled: Optional[bool] = None
    wheel_diameter: Optional[str] = None

    class Config:
        from_attributes = True


class ProfileOut(BaseModel):
    id: int
    name: Optional[str] = None
    email: Optional[str] = None
    phone: str
    pin_is_set: bool = False
    cars: List[CarOut] = []


# ----------------------------------------------------------------------
# Запись
# ----------------------------------------------------------------------

class SlotOut(BaseModel):
    """Свободное окно, которое можно предложить клиенту."""
    at: datetime
    free_posts: int


class DayOut(BaseModel):
    day: date
    is_closed: bool
    opens_at: str
    closes_at: str
    posts: int
    slots: List[SlotOut] = []

    # День закрыт не потому, что выходной, а потому, что комплект со
    # склада к нему не успеют привезти. Приложение скажет об этом
    # словами, а не оставит человека гадать
    storage_too_soon: bool = False


class BookingIn(BaseModel):
    # Куда записываться. Пусто — когда точка одна
    shop: Optional[str] = None
    at: datetime
    license_plate: str
    wheels_assembled: Optional[bool] = None
    comment: Optional[str] = None
    # Комплекты со склада, которые достать к приезду. Доступно только
    # вошедшему: что у кого лежит — закрытые сведения
    storage_ids: List[int] = []


class AppointmentOut(BaseModel):
    id: int
    at: datetime
    duration_minutes: int
    license_plate: Optional[str] = None
    wheels_assembled: Optional[bool] = None
    status: str
    status_title: str
    # Пока цех не забрал заявку, клиент видит «подтверждаем»
    is_confirmed: bool
    comment: Optional[str] = None


# ----------------------------------------------------------------------
# Хранение
# ----------------------------------------------------------------------

class StoredSetOut(BaseModel):
    id: int
    license_plate: Optional[str] = None
    storage_type: Optional[str] = None
    wheel_type: Optional[str] = None
    diameter: Optional[str] = None
    brand: Optional[str] = None
    accepted_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    days_left: Optional[int] = None
    status: str
    requested_for: Optional[datetime] = None
    request_state: Optional[str] = None


class StorageRequestIn(BaseModel):
    at: datetime = Field(..., description='Когда клиент приедет за комплектом')


# ----------------------------------------------------------------------
# История
# ----------------------------------------------------------------------

class VisitOut(BaseModel):
    id: int
    at: datetime
    license_plate: Optional[str] = None
    total_amount: float
    services: List[str] = []
    recommendations: Optional[str] = None
    is_warranty: bool


# ----------------------------------------------------------------------
# Очередь
# ----------------------------------------------------------------------

class QueueOut(BaseModel):
    shift_is_open: bool
    cars_in_work: int
    cars_waiting: int
    open_posts: int
    free_in_minutes: Optional[int] = None
    taken_at: Optional[datetime] = None
    # Данные пришли из цеха давно — значит, показывать их как «сейчас» нельзя
    is_stale: bool
    note: str
