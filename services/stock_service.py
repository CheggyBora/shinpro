"""
Склад (docs/stock.md): позиции, приход, расход материалов по услугам,
списание при пробитии наряда и возврат при возврате.

Включается в настройках (`stock_enabled`), по умолчанию выключен — тогда
ничего здесь не вызывается, а расходник у услуги остаётся суммой в
рублях, как было.

Минус допустим: продажу из-за пустой полки не останавливаем — на ней
бывает то, что забыли оприходовать. Но когда позиция ушла в минус,
главному один раз уходит сообщение в Telegram (тем, кому идёт сводка).
«Мало» — только отметка жёлтым.
"""
import hashlib
import json

from logger import log
from models import Service, WorkOrder, WorkOrderItem
from models.stock import StockItem, ServiceMaterial, StockMove, GOODS, MATERIAL, UNITS
from utils import get_moscow_time, as_naive

ENABLED_KEY = 'stock_enabled'


def stock_on(db):
    from services.settings_service import SettingsService
    value = SettingsService(db).get(ENABLED_KEY)
    return str(value or '0').strip().lower() in ('1', 'true', 'yes', 'да', 'вкл')


def fmt_qty(value, unit=''):
    """146 шт, 1,5 л, −0,4 л — как люди пишут."""
    value = round(float(value or 0), 3)
    text = f'{value:.3f}'.rstrip('0').rstrip('.').replace('.', ',')
    if text.startswith('-'):
        text = '−' + text[1:]
    return f'{text} {unit}'.strip()


class StockError(ValueError):
    """Понятная человеку причина, почему не вышло."""


class StockService:
    def __init__(self, db):
        self.db = db

    def enabled(self):
        return stock_on(self.db)

    def set_enabled(self, on):
        from services.settings_service import SettingsService
        SettingsService(self.db).set(ENABLED_KEY, '1' if on else '0')
        # Главное окно показывает или прячет раздел «Склад»
        from services import directions
        if directions.ON_CHANGE is not None:
            try:
                directions.ON_CHANGE()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Позиции
    # ------------------------------------------------------------------

    def items(self, direction=None, kind=None, problems_only=False):
        query = self.db.query(StockItem).filter(StockItem.is_active.isnot(False))
        if direction:
            query = query.filter(StockItem.direction == direction)
        if kind:
            query = query.filter(StockItem.kind == kind)
        rows = query.order_by(StockItem.name).all()
        if problems_only:
            rows = [r for r in rows if r.state != 'ok']
        order = {'neg': 0, 'low': 1, 'ok': 2}
        return sorted(rows, key=lambda r: (order[r.state], r.name.lower()))

    def get(self, item_id):
        return self.db.query(StockItem).filter(StockItem.id == item_id).first()

    def problems_count(self):
        return sum(1 for r in self.items() if r.state != 'ok')

    def save_item(self, item=None, **fields):
        name = (fields.get('name') or (item.name if item else '') or '').strip()
        if not name:
            raise StockError('Напишите название позиции')
        try:
            price = float(str(fields.get('price', item.price if item else '')).replace(',', '.'))
        except ValueError:
            raise StockError('Цена — числом, например 150')
        if price < 0:
            raise StockError('Цена не может быть меньше нуля')
        purchase = fields.get('purchase_price', item.purchase_price if item else None)
        if purchase in ('', None):
            purchase = None
        else:
            try:
                purchase = float(str(purchase).replace(',', '.'))
            except ValueError:
                raise StockError('Закупка — числом или пусто')
        unit = fields.get('unit') or (item.unit if item else 'шт')
        if unit not in UNITS:
            raise StockError('Неизвестная единица')

        def number(key, default):
            raw = fields.get(key, default)
            try:
                return float(str(raw).replace(',', '.')) if raw not in ('', None) else 0.0
            except ValueError:
                raise StockError('Остаток и минимум — числами')

        if item is None:
            import uuid
            direction = fields.get('direction')
            kind = fields.get('kind')
            if direction not in ('tire', 'wash'):
                raise StockError('Выберите, шиномонтаж это или мойка')
            if kind not in (GOODS, MATERIAL):
                raise StockError('Выберите: товар или материал')
            item = StockItem(uid=str(uuid.uuid4()), direction=direction, kind=kind, name=name)
            self.db.add(item)
            item.quantity = number('quantity', 0)
        item.name = name
        item.unit = unit
        item.price = price
        item.purchase_price = purchase
        item.min_quantity = number('min_quantity', item.min_quantity)
        item.updated_at = get_moscow_time()
        self.db.flush()
        if item.kind == GOODS:
            self._sync_goods_service(item)
        self.db.commit()
        return item

    def _sync_goods_service(self, item):
        """Товар продаётся в наряде как позиция прайса — держим её в лад."""
        service = self.db.query(Service).filter(Service.id == item.service_id).first() \
            if item.service_id else None
        if service is None:
            # Товар уже есть в прайсе — берём его, а не заводим второй такой же
            service = self.db.query(Service).filter(
                Service.is_goods.is_(True), Service.name == item.name,
                Service.direction == item.direction, Service.is_active.isnot(False)).first()
            if service is not None:
                item.service_id = service.id
        if service is None:
            service = Service(name=item.name, vehicle_type='all', direction=item.direction,
                              is_goods=True, is_active=True)
            self.db.add(service)
            self.db.flush()
            item.service_id = service.id
        service.name = item.name
        service.flat_price = item.price
        service.purchase_price = item.purchase_price or 0.0
        service.is_goods = True
        service.is_active = bool(item.is_active)
        service.direction = item.direction

    def remove_item(self, item):
        item.is_active = False
        item.updated_at = get_moscow_time()
        if item.service_id:
            service = self.db.query(Service).filter(Service.id == item.service_id).first()
            if service is not None:
                service.is_active = False
        self.db.query(ServiceMaterial).filter(ServiceMaterial.item_id == item.id).delete()
        self.db.commit()

    def receive(self, item, amount, purchase_price=None, note=None):
        """Приход: привезли — добавили к остатку."""
        try:
            amount = float(str(amount).replace(',', '.'))
        except ValueError:
            raise StockError('Сколько пришло — числом')
        if amount <= 0:
            raise StockError('Сколько пришло — больше нуля')
        if purchase_price not in (None, ''):
            try:
                item.purchase_price = float(str(purchase_price).replace(',', '.'))
            except ValueError:
                raise StockError('Закупка — числом или пусто')
            if item.kind == GOODS:
                self._sync_goods_service(item)
        self._move(item, amount, 'receive', note=note)
        self.db.commit()
        return item

    def correct(self, item, quantity, note='Пересчёт'):
        """Пересчитали полку — поставить фактический остаток."""
        quantity = float(str(quantity).replace(',', '.'))
        self._move(item, quantity - (item.quantity or 0), 'correct', note=note)
        self.db.commit()

    def history(self, item, limit=50):
        return self.db.query(StockMove).filter(StockMove.item_id == item.id).order_by(
            StockMove.id.desc()).limit(limit).all()

    def _move(self, item, change, reason, order_id=None, note=None):
        before = item.quantity or 0
        item.quantity = round(before + change, 4)
        item.updated_at = get_moscow_time()
        self.db.add(StockMove(item_id=item.id, change=round(change, 4), reason=reason,
                              order_id=order_id, note=note))
        return before, item.quantity

    # ------------------------------------------------------------------
    # Расход по услугам
    # ------------------------------------------------------------------

    def recipe(self, service_id):
        rows = self.db.query(ServiceMaterial).filter(ServiceMaterial.service_id == service_id).all()
        result = []
        for row in rows:
            item = self.get(row.item_id)
            if item is not None and item.is_active:
                result.append((row, item))
        return result

    def set_material(self, service_id, item_id, quantity):
        quantity = float(str(quantity).replace(',', '.'))
        if quantity <= 0:
            raise StockError('Расход — больше нуля')
        row = self.db.query(ServiceMaterial).filter(
            ServiceMaterial.service_id == service_id, ServiceMaterial.item_id == item_id).first()
        if row is None:
            row = ServiceMaterial(service_id=service_id, item_id=item_id)
            self.db.add(row)
        row.quantity = quantity
        self.db.commit()
        return row

    def remove_material(self, service_id, item_id):
        self.db.query(ServiceMaterial).filter(
            ServiceMaterial.service_id == service_id, ServiceMaterial.item_id == item_id).delete()
        self.db.commit()

    def recipe_cost(self, service_id):
        """Расходник одного выполнения в рублях: расход × отпускная цена."""
        return round(sum(row.quantity * (item.price or 0) for row, item in self.recipe(service_id)), 2)

    def consumable_cost_for(self, service):
        """
        Расходник строки наряда. Склад включён и у услуги прописан расход —
        по расходу; иначе — сумма вручную, как было.
        """
        if service.is_goods:
            return None
        if self.enabled() and self.recipe(service.id):
            return self.recipe_cost(service.id)
        return None

    # ------------------------------------------------------------------
    # Наряд
    # ------------------------------------------------------------------

    def _plan(self, order_id):
        """Что списать по наряду: {item_id: количество}."""
        plan = {}
        lines = self.db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == order_id).all()
        for line in lines:
            count = line.quantity or 1
            if getattr(line, 'is_goods', False):
                item = self.db.query(StockItem).filter(
                    StockItem.service_id == line.service_id).first()
                if item is not None:
                    plan[item.id] = plan.get(item.id, 0) + count
                continue
            for row, item in self.recipe(line.service_id):
                plan[item.id] = plan.get(item.id, 0) + row.quantity * count
        return plan

    def write_off_order(self, order_id):
        """Пробили наряд — списать материалы и товары. Повторно не списывает."""
        if not self.enabled():
            return []
        done = self.db.query(StockMove).filter(
            StockMove.order_id == order_id, StockMove.reason == 'order').first()
        if done is not None:
            return []
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        gone_negative = []
        for item_id, amount in self._plan(order_id).items():
            item = self.get(item_id)
            if item is None:
                continue
            before, after = self._move(item, -amount, 'order', order_id=order_id)
            if before >= 0 > after:
                gone_negative.append(item)
        self.db.commit()
        for item in gone_negative:
            self._tell_negative(item, order)
        return gone_negative

    def return_order(self, order_id):
        """Возврат наряда целиком — вернуть списанное на склад."""
        moves = self.db.query(StockMove).filter(
            StockMove.order_id == order_id, StockMove.reason == 'order').all()
        if not moves or self.db.query(StockMove).filter(
                StockMove.order_id == order_id, StockMove.reason == 'refund').first():
            return 0
        for move in moves:
            item = self.get(move.item_id)
            if item is not None:
                self._move(item, -move.change, 'refund', order_id=order_id)
        self.db.commit()
        return len(moves)

    def _tell_negative(self, item, order):
        """Ушло в минус — главному в Telegram, тем, кому идёт сводка."""
        try:
            from services import telegram_outbox
            plate = order.car.license_plate if order is not None and order.car else ''
            text = (f'<b>Склад: ушло в минус</b>\n{item.name} — {fmt_qty(item.quantity, item.unit)}'
                    + (f'\nНаряд №{order.id} · {plate}' if order is not None else ''))
            telegram_outbox.queue(self.db, 'stock', text)
        except Exception as e:
            log.warning(f'Сообщение о минусе на складе не поставлено: {e}')

    # ------------------------------------------------------------------
    # Обмен с сервером: снимок для дашборда
    # ------------------------------------------------------------------

    def snapshot(self):
        items = [{
            'uid': r.uid, 'name': r.name, 'direction': r.direction, 'kind': r.kind,
            'unit': r.unit, 'quantity': round(r.quantity or 0, 4),
            'min_quantity': round(r.min_quantity or 0, 4), 'price': r.price,
            'purchase_price': r.purchase_price,
            'updated_at': as_naive(r.updated_at).replace(microsecond=0).isoformat() if r.updated_at else None,
        } for r in self.db.query(StockItem).filter(StockItem.is_active.isnot(False)).all()]
        return {'enabled': self.enabled(), 'items': items}

    @staticmethod
    def fingerprint(snapshot):
        return hashlib.sha1(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
