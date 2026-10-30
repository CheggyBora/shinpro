"""
Календарь задач и контрагенты (docs/calendar.md).

Задача живёт и в цеху, и на сервере: её ставят приёмщик, владелец из
дашборда, сама программа (склад, покраска) и кабинет клиента. Чтобы
это была одна и та же задача, у неё есть uid — одинаковый с обеих
сторон. Удалённую не стираем, а помечаем: иначе вторая сторона так и не
узнала бы, что её удалили, и вернула бы обратно при обмене.
"""
import uuid

from sqlalchemy import Column, Integer, String, Text, Date, DateTime, Boolean, Float

from config import Base
from utils import get_moscow_time

# Разделы — в том порядке, в каком их показываем. У мойки свой слой
# календаря со своими разделами (docs/calendar.md)
WORK, STORAGE, TIRES, PAINT, SUPPLY = 'work', 'storage', 'tires', 'paint', 'supply'
# Ниже — встроенные значения. Владелец переименовывает, скрывает и
# добавляет свои разделы (решение 30.10.2026): services/task_sections
# переписывает эти словари на месте, и все, кто их импортировал, видят
# новое без перезапуска
CATEGORIES_BY_DIRECTION = {'tire': [WORK, STORAGE, TIRES, PAINT], 'wash': [WORK, SUPPLY]}
# Все разделы направления, со скрытыми: у старой задачи раздел могли
# скрыть, а поправить её всё равно надо
KNOWN_BY_DIRECTION = {'tire': [WORK, STORAGE, TIRES, PAINT], 'wash': [WORK, SUPPLY]}
CATEGORIES = [WORK, STORAGE, TIRES, PAINT, SUPPLY]
CATEGORY_TITLES = {WORK: 'Рабочая', STORAGE: 'Хранение', TIRES: 'Шины', PAINT: 'Покраска',
                   SUPPLY: 'Поставки'}
# Цвета разделов (текст, фон) — те же, что в дашборде
CATEGORY_COLORS = {
    WORK: ('#1d4ed8', '#dbeafe'),
    STORAGE: ('#0f766e', '#ccfbf1'),
    TIRES: ('#c2410c', '#ffedd5'),
    PAINT: ('#6d28d9', '#ede9fe'),
    SUPPLY: ('#b45309', '#fef3c7'),
}


def categories_of(direction):
    """Разделы, которые предлагаем в новой задаче, — без скрытых."""
    return CATEGORIES_BY_DIRECTION.get(direction or 'tire', CATEGORIES_BY_DIRECTION['tire'])


def known_categories(direction):
    """Все разделы направления, со скрытыми, — для проверки задачи."""
    return KNOWN_BY_DIRECTION.get(direction or 'tire', KNOWN_BY_DIRECTION['tire'])

SOURCE_SHOP, SOURCE_DASHBOARD, SOURCE_AUTO, SOURCE_CABINET = 'shop', 'dashboard', 'auto', 'cabinet'

# Вид записи: задача — с галочкой, напоминает и переходит на завтра;
# комментарий — просто запись на день (решение владельца 29.10.2026)
KIND_TASK, KIND_NOTE = 'task', 'note'
KINDS = (KIND_TASK, KIND_NOTE)


def new_uid():
    return str(uuid.uuid4())


class CalendarTask(Base):
    __tablename__ = 'calendar_tasks'

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(String(40), nullable=False, unique=True, index=True, default=new_uid)

    category = Column(String(16), nullable=False, default=WORK)
    # Слой календаря: шиномонтаж или мойка
    direction = Column(String(10), nullable=False, default='tire', server_default='tire')
    due_date = Column(Date, nullable=False, index=True)
    due_time = Column(String(5), nullable=True)          # «10:00» или пусто
    end_time = Column(String(5), nullable=True)          # до скольки, без «с» не бывает
    kind = Column(String(10), nullable=False, default='task', server_default='task')

    title = Column(String(200), nullable=False, default='')
    note = Column(Text, nullable=True)

    # Машина: по номеру открывается всё по ней, и задача всплывает в её
    # наряде. Имя и телефон — для показа, когда клиента нет в базе
    license_plate = Column(String(20), nullable=True, index=True)
    client_name = Column(String(200), nullable=True)
    client_phone = Column(String(50), nullable=True)

    counterparty_uid = Column(String(40), nullable=True)
    storage_ref = Column(String(50), nullable=True)      # номер комплекта
    amount = Column(Float, nullable=True)                # покраска

    done_at = Column(DateTime(timezone=True), nullable=True)
    done_by = Column(String(100), nullable=True)
    deleted = Column(Boolean, nullable=False, default=False)

    source = Column(String(16), nullable=False, default=SOURCE_SHOP)
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=get_moscow_time)
    updated_at = Column(DateTime(timezone=True), default=get_moscow_time)

    # Когда последний раз отдали серверу. Пусто или раньше updated_at —
    # правка ещё не ушла
    synced_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<Задача {self.due_date} {self.due_time or ''} {self.category}: {self.title}>"


class Counterparty(Base):
    __tablename__ = 'counterparties'

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(String(40), nullable=False, unique=True, index=True, default=new_uid)
    name = Column(String(200), nullable=False)
    direction = Column(String(10), nullable=False, default='tire', server_default='tire')
    kind = Column(String(200), nullable=True)            # чем занимается
    contact = Column(String(200), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(200), nullable=True)
    address = Column(String(300), nullable=True)
    inn = Column(String(20), nullable=True)
    note = Column(Text, nullable=True)
    # Ник в Telegram без «@»: задачу с этим контрагентом шлём и ему,
    # если он писал боту (решение владельца 29.10.2026)
    telegram = Column(String(64), nullable=True)
    deleted = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), default=get_moscow_time)
    synced_at = Column(DateTime(timezone=True), nullable=True)


class TelegramOutbox(Base):
    """
    Сообщение в Telegram, которое ещё не ушло.

    Склад и покраска пишут в Telegram сразу, но в цеху бывает без
    интернета. Сообщение ложится сюда и досылается, когда связь вернётся:
    водитель должен узнать о комплекте, даже если отправили в обрыв.
    """
    __tablename__ = 'telegram_outbox'

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(20), nullable=False)            # storage / paint / …
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=get_moscow_time)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String(300), nullable=True)
    # Кому лично: ник контрагента. Пусто — получателям вида
    target = Column(String(64), nullable=True)
    # Кому именно — номера чатов через запятую: в задаче отметили людей
    # сами (блок «Уведомить», 30.10.2026). Пусто — получателям вида
    chats = Column(Text, nullable=True)
