"""
Магазин (решение владельца 08.11.2026): карточки товаров и продажа.

Карточка — позиция склада с направлением «shop»: название, категория,
артикул, цена, закупка, остаток, фото по желанию и бонус продавцу. Как
любой товар склада, она сама стоит в прайсе — поэтому её можно добавить
в любой наряд, а продажа считается, списывается и попадает в отчёты
тем же путём, что и наряд.

Продажа без машины — наряд на служебную «машину» МАГАЗИН: так она
проходит кассу, чек, возврат, отчёты и обмен с сервером без отдельного
пути. Клиента у такой продажи нет.
"""
import os
import shutil

from models import Car, WorkOrder
from models.stock import StockItem, GOODS
from services import directions
from services.stock_service import StockService, StockError

# «Машина» продаж без машины. Номер — словом: в истории сразу видно,
# что это продажа, а не наряд
SALE_PLATE = 'МАГАЗИН'
PHOTO_DIR = 'shop'
PHOTO_SIZE = 480


class ShopService:
    def __init__(self, db):
        self.db = db
        self.stock = StockService(db)

    # ------------------------------------------------------------------
    # Карточки
    # ------------------------------------------------------------------

    def cards(self, text='', category=None):
        """Карточки магазина: поиск по названию и артикулу, фильтр по категории."""
        query = self.db.query(StockItem).filter(
            StockItem.direction == directions.SHOP, StockItem.kind == GOODS,
            StockItem.is_active.isnot(False))
        rows = query.order_by(StockItem.category, StockItem.name).all()
        needle = (text or '').strip().lower()
        if category:
            rows = [r for r in rows if (r.category or '') == category]
        if needle:
            rows = [r for r in rows if needle in r.name.lower()
                    or (r.sku and needle in r.sku.lower())
                    or (r.category and needle in r.category.lower())]
        return rows

    def categories(self):
        rows = self.db.query(StockItem.category).filter(
            StockItem.direction == directions.SHOP, StockItem.is_active.isnot(False),
            StockItem.category.isnot(None)).distinct().all()
        return sorted({row[0] for row in rows if row[0]})

    def save_card(self, card=None, photo_from=None, **fields):
        """Завести или поправить карточку. photo_from — файл фото, необязательно."""
        fields.setdefault('direction', directions.SHOP)
        fields['kind'] = GOODS
        card = self.stock.save_item(card, **fields)
        if photo_from:
            card.photo = self._store_photo(card, photo_from)
            self.db.commit()
        return card

    def remove_photo(self, card):
        card.photo = None
        self.db.commit()

    # ------------------------------------------------------------------
    # Фото — рядом с базой, уменьшенной копией
    # ------------------------------------------------------------------

    @staticmethod
    def photo_folder():
        # Рядом с обложками нарядов: photos/shop возле базы
        from services.arrival_service import covers_dir
        folder = os.path.join(os.path.dirname(covers_dir()), PHOTO_DIR)
        os.makedirs(folder, exist_ok=True)
        return folder

    def photo_path(self, card):
        if not card or not card.photo:
            return None
        path = os.path.join(self.photo_folder(), card.photo)
        return path if os.path.exists(path) else None

    def _store_photo(self, card, source):
        """Уменьшить и положить в photos/shop. Не картинка — StockError."""
        name = f'{card.uid}.jpg'
        target = os.path.join(self.photo_folder(), name)
        try:
            from PIL import Image
            with Image.open(source) as image:
                image = image.convert('RGB')
                image.thumbnail((PHOTO_SIZE, PHOTO_SIZE))
                image.save(target, 'JPEG', quality=85)
        except ImportError:
            shutil.copyfile(source, target)
        except Exception:
            raise StockError('Это не похоже на фото — выберите картинку (jpg, png)')
        return name

    # ------------------------------------------------------------------
    # Продажа без машины
    # ------------------------------------------------------------------

    def sale_car(self):
        car = self.db.query(Car).filter(Car.license_plate == SALE_PLATE).first()
        if car is None:
            car = Car(license_plate=SALE_PLATE)
            self.db.add(car)
            self.db.commit()
        return car

    def create_sale(self, lines, seller_id=None):
        """
        Продажа без машины: [(карточка, количество)] → наряд-продажа,
        ещё не оплаченный. Пробивают его как наряд (SalaryService).
        """
        from services.order_service import OrderService
        from services.shift_service import ShiftService
        lines = [(card, int(qty)) for card, qty in lines if card is not None and int(qty) > 0]
        if not lines:
            raise StockError('Добавьте в продажу хотя бы один товар')
        # Процент с продаж включён — продаёт один человек, его и выбирают
        # (решение владельца 09.11.2026). Выключен — продавец не нужен
        if directions.shop_pay_on(self.db):
            seller_id = seller_id or OrderService(self.db)._default_seller()
            if not seller_id:
                raise ValueError('Выберите, кто продал')
        else:
            seller_id = None
        current =ShiftService(self.db).get_current_shift()
        order = WorkOrder(car_id=self.sale_car().id, client_id=None, wheel_diameter='',
                          vehicle_type='car', status='draft', directions=directions.SHOP,
                          shift_id=current.id if current else None)
        self.db.add(order)
        self.db.commit()
        orders = OrderService(self.db)
        try:
            for card, qty in lines:
                orders.add_service_to_order(order.id, card.service_id, employee_id=seller_id,
                                            quantity=qty)
        except Exception:
            self.db.rollback()
            self.db.delete(order)
            self.db.commit()
            raise
        self.db.refresh(order)
        return order

    @staticmethod
    def is_sale(order):
        """Продажа без машины, а не наряд."""
        return (order.directions or '') == directions.SHOP
