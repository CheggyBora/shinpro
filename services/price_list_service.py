"""
Прайс-лист: позиции целиком, а не строки по типам машин.

В базе одна услуга — это несколько строк: «Балансировка» для легкового,
джипа и категории С, у каждой свои цены по диаметрам. Цены и правда
разные, а вот время, расходник, вид и скидка почти всегда одни и те же —
и править их по трём строкам было мучением (решение владельца 28.10.2026).

Здесь всё, что делается с позицией как с целым: добавить, переименовать,
скрыть, вернуть, поменять свойство сразу у всех типов машин. Удаления
нет: позиция стоит в старых нарядах, и история должна остаться целой.
"""
from models import Service
from services import directions

TYPES = (('car', 'Легковой'), ('suv', 'Джип'), ('truck', 'Категория С'))
TYPE_TITLES = dict(TYPES, all='Любой')
SHORT_TITLES = {'car': 'Легк', 'suv': 'Джип', 'truck': 'Кат.С', 'all': 'любые'}
RADII = tuple(range(13, 25))
# У категории С в прайсе только R15–R19 — как в таблице цен
TRUCK_RADII = tuple(range(15, 20))

FLAT, BY_RADIUS, EDITABLE = 'flat', 'radius', 'editable'


class PriceError(ValueError):
    """Понятная владельцу причина, почему позицию не сохранить."""


def radii_of(vehicle_type):
    return TRUCK_RADII if vehicle_type == 'truck' else RADII


def _order(row):
    return [key for key, _title in TYPES].index(row.vehicle_type) \
        if row.vehicle_type in dict(TYPES) else -1


class PriceListService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Чтение
    # ------------------------------------------------------------------

    def rows(self, name, direction=None, active=True):
        query = self.db.query(Service).filter(Service.name == name)
        if direction:
            query = query.filter(Service.direction == direction)
        if active is not None:
            query = query.filter(Service.is_active.isnot(False) if active
                                 else Service.is_active.is_(False))
        return sorted(query.all(), key=_order)

    def groups(self, direction=None):
        """[(направление, имя, [строки по типам])] — по одной на позицию."""
        query = self.db.query(Service).filter(Service.is_active.isnot(False))
        if direction:
            query = query.filter(Service.direction == direction)
        found = {}
        for row in query.order_by(Service.name).all():
            found.setdefault((row.direction or directions.TIRE, row.name), []).append(row)
        return [(key[0], key[1], sorted(rows, key=_order)) for key, rows in found.items()]

    def hidden(self, direction=directions.TIRE):
        """Скрытые позиции — те, у которых не осталось ни одной видимой строки."""
        visible = {name for (name,) in self.db.query(Service.name).filter(
            Service.direction == direction, Service.is_active.isnot(False)).distinct()}
        names = {name for (name,) in self.db.query(Service.name).filter(
            Service.direction == direction, Service.is_active.is_(False)).distinct()}
        return sorted(names - visible)

    def exists(self, name, direction):
        return bool(self.rows(name, direction))

    # ------------------------------------------------------------------
    # Добавление
    # ------------------------------------------------------------------

    def _check_name(self, name, direction):
        name = (name or '').strip()
        if not name:
            raise PriceError('Впишите название')
        if len(name) > 200:
            raise PriceError('Название слишком длинное')
        if self.exists(name, direction):
            raise PriceError(f'«{name}» уже есть в прайсе')
        if name in self.hidden(direction):
            raise PriceError(f'«{name}» скрыта — верните её кнопкой «Скрытые»')
        return name

    def add_service(self, name, direction=directions.TIRE, mode=BY_RADIUS,
                    prices=None, flat_price=None, is_extra=True,
                    consumable_cost=0.0, minutes=0):
        """
        Новая услуга.

        prices — {тип машины: {радиус: цена}}. Не заполнили джип или
        категорию С — у них цены как у легкового. Если ни одной своей цены
        у джипа и категории С нет, строка одна — «для любых машин»: так
        заведены почти все допы, и плодить три одинаковые незачем.
        """
        name = self._check_name(name, direction)
        common = dict(direction=direction, is_active=True, is_extra=bool(is_extra),
                      consumable_cost=float(consumable_cost or 0),
                      duration_minutes=int(minutes or 0))

        if direction == directions.WASH:
            # У мойки цена по классу машины — её ставят в окне «Мойка»
            row = Service(name=name, vehicle_type='all', **common)
            self.db.add(row)
            self.db.commit()
            return [row]

        if mode == FLAT:
            if flat_price is None or float(flat_price) <= 0:
                raise PriceError('Впишите цену')
            row = Service(name=name, vehicle_type='all', flat_price=float(flat_price), **common)
            self.db.add(row)
            self.db.commit()
            return [row]

        if mode == EDITABLE:
            row = Service(name=name, vehicle_type='all', editable_price=True, **common)
            self.db.add(row)
            self.db.commit()
            return [row]

        prices = prices or {}
        car = {int(r): float(v) for r, v in (prices.get('car') or {}).items() if v is not None}
        if not any(car.values()):
            raise PriceError('Впишите цены для легкового хотя бы на один радиус')
        own = {kind: {int(r): float(v) for r, v in (prices.get(kind) or {}).items()
                      if v is not None}
               for kind in ('suv', 'truck')}

        def row_for(vehicle_type, values):
            row = Service(name=name, vehicle_type=vehicle_type, **common)
            for radius in RADII:
                setattr(row, f'price_r{radius}', values.get(radius, car.get(radius, 0.0)))
            return row

        if not any(own['suv'].values()) and not any(own['truck'].values()):
            rows = [row_for('all', car)]
        else:
            rows = [row_for('car', car), row_for('suv', own['suv']),
                    row_for('truck', own['truck'])]
        self.db.add_all(rows)
        self.db.commit()
        return rows

    def add_goods(self, name, price, purchase=None, direction=directions.TIRE):
        """Товар: одна цена на любую машину. Склад включён — встаёт и туда."""
        name = self._check_name(name, direction)
        try:
            price = float(str(price).replace(',', '.'))
        except (TypeError, ValueError):
            raise PriceError('Цена продажи — числом')
        if price <= 0:
            raise PriceError('Впишите цену продажи')
        if purchase not in (None, ''):
            try:
                purchase = float(str(purchase).replace(',', '.'))
            except ValueError:
                raise PriceError('Закупка — числом или пусто')
        else:
            purchase = None

        from services.stock_service import StockService
        stock = StockService(self.db)
        if stock.enabled():
            from models.stock import GOODS
            item = stock.save_item(None, direction=direction, kind=GOODS, name=name,
                                   price=price, purchase_price=purchase, unit='шт')
            return self.db.query(Service).filter(Service.id == item.service_id).first()

        row = Service(name=name, vehicle_type='all', direction=direction, is_goods=True,
                      is_extra=True, flat_price=price, purchase_price=purchase or 0.0,
                      is_active=True)
        self.db.add(row)
        self.db.commit()
        return row

    # ------------------------------------------------------------------
    # Переименовать, скрыть, вернуть
    # ------------------------------------------------------------------

    def rename(self, name, new_name, direction=directions.TIRE):
        new_name = (new_name or '').strip()
        if new_name == name:
            return
        new_name = self._check_name(new_name, direction)
        rows = self.db.query(Service).filter(Service.name == name,
                                             Service.direction == direction).all()
        if not rows:
            raise PriceError(f'«{name}» не найдена')
        for row in rows:
            row.name = new_name
        self._rename_in_settings(name, new_name)
        self.db.commit()

    def _rename_in_settings(self, old, new):
        """Имя хранится ещё в раскладке кнопок, вопросе про колесо и категориях мастеров."""
        from services.service_layout import _read_saved, save_layout
        from services.wheel_service import WheelSettings
        from models.employee_role import EmployeeRole

        layout = _read_saved(self.db)
        if layout and any(old in column for column in layout):
            save_layout(self.db, [[new if n == old else n for n in column] for column in layout])

        wheels = WheelSettings(self.db)
        names = wheels.names()
        if old in names:
            wheels.set_names([new if n == old else n for n in names])

        for role in self.db.query(EmployeeRole).all():
            if old in role.excluded:
                role.set_excluded([new if n == old else n for n in role.excluded])

    def hide(self, name, direction=directions.TIRE):
        """Скрыть из прайса и кнопок наряда. В старых нарядах позиция остаётся."""
        rows = self.rows(name, direction)
        for row in rows:
            row.is_active = False
        self.db.commit()
        return len(rows)

    def restore(self, name, direction=directions.TIRE):
        rows = self.rows(name, direction, active=False)
        for row in rows:
            row.is_active = True
        self.db.commit()
        return len(rows)

    # ------------------------------------------------------------------
    # Свойства — сразу у всех типов машин
    # ------------------------------------------------------------------

    @staticmethod
    def cost_field(row):
        return 'purchase_price' if row.is_goods else 'consumable_cost'

    def set_values(self, rows, field, values):
        """
        Поставить свойство. values — одно значение на все строки или
        {id строки: значение}, когда у типов машин оно своё.
        Возвращает [(строка, было, стало)] — только то, что поменялось.
        """
        changed = []
        for row in rows:
            value = values.get(row.id) if isinstance(values, dict) else values
            if value is None and field != 'flat_price':
                continue
            target = self.cost_field(row) if field == 'cost' else field
            old = getattr(row, target)
            if old != value:
                setattr(row, target, value)
                changed.append((row, old, value))
        if changed:
            self.db.commit()
        return changed


def merge_duplicates(db):
    """
    Одна позиция — одна строка на тип машины. Если строк на один тип две
    (так в прайсе оказался второй «Шиномонтаж» для легкового с ценой только
    на R16), оставляем ту, где заполнено больше цен, а лишнюю скрываем:
    в нарядах наряд брал любую из двух, как повезёт.
    """
    rows = db.query(Service).filter(Service.is_active.isnot(False)).order_by(Service.id).all()
    seen = {}
    for row in rows:
        seen.setdefault((row.direction, row.name, row.vehicle_type), []).append(row)
    hidden = []
    for same in seen.values():
        if len(same) < 2:
            continue
        keep = max(same, key=lambda r: (sum(1 for n in RADII if getattr(r, f'price_r{n}')),
                                        -r.id))
        for row in same:
            if row is not keep:
                row.is_active = False
                hidden.append(row)
    return hidden
