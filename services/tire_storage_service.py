"""
Хранение шин: приёмка, поиск и выдача комплектов.

Раньше каждый метод открывал СВОЮ сессию базы данных, а остальная
программа работала в другой. Из-за этого запись, только что созданная
здесь, не была видна остальному коду, и её приходилось перезапрашивать
вручную. Теперь сервис работает в той же сессии, что и весь интерфейс.
"""
from datetime import timedelta

from models import TireStorage, Settings
from utils import get_moscow_time, normalize_plate

# Цены хранения по размеру, если в настройках ничего не задано
DEFAULT_STORAGE_PRICES = {
    13: 4000, 14: 4000, 15: 4000,
    16: 5000, 17: 5000, 18: 5000,
    19: 6000, 20: 6000,
    21: 8000, 22: 8000, 23: 8000, 24: 8000,
}


class TireStorageService:
    # Отметка о том, что сроки уже проставлены разом. Живёт в настройках,
    # а не в коде: иначе переустановка программы прошлась бы по складу
    # второй раз
    FILLED_KEY = 'storage_deadlines_filled'

    def __init__(self, db):
        self.db = db

    def calculate_price(self, diameter):
        """Цена хранения для конкретного размера шин."""
        try:
            diameter_num = int(str(diameter).upper().replace('R', ''))
        except (TypeError, ValueError):
            return 0.0

        if diameter_num not in DEFAULT_STORAGE_PRICES:
            return 0.0

        setting_key = f'storage_price_r{diameter_num}'
        price_setting = self.db.query(Settings).filter(Settings.key == setting_key).first()

        if price_setting and price_setting.value:
            try:
                return float(price_setting.value)
            except ValueError:
                pass

        return float(DEFAULT_STORAGE_PRICES[diameter_num])

    def storage_months(self):
        """Срок хранения в месяцах. Ноль — срок не ставим."""
        from services.settings_service import SettingsService

        return SettingsService(self.db).get_int('storage_months', '6')

    def deadline_for(self, accepted, months=None):
        """
        До какого числа лежит комплект, принятый в этот день.

        Месяц считаем как 30 дней, а не календарным сдвигом: разница
        в пару дней никого не касается, зато нет случая «приняли
        31 августа, а срок — 31 февраля».
        """
        if accepted is None:
            return None

        months = self.storage_months() if months is None else months
        if not months:
            return None

        return accepted + timedelta(days=30 * months)

    def set_deadline(self, storage_id, when):
        """
        Поставить комплекту свой срок.

        Договорились с человеком иначе — значит в базе должно стоять то,
        о чём договорились. Напоминание уйдёт по этому числу.
        """
        storage = self.get_storage_by_id(storage_id)
        if storage is None:
            return None

        storage.expires_at = when
        self.db.commit()
        self.db.refresh(storage)
        return storage

    def expiring(self, days=7):
        """
        Комплекты, у которых срок на исходе или уже вышел.

        Нужно и цеху — видеть, кому звонить, — и обмену: сервер по этим
        же числам предупреждает владельцев сам.
        """
        now = get_moscow_time()
        edge = now + timedelta(days=days)

        rows = self.db.query(TireStorage).filter(
            TireStorage.status == 'stored',
            TireStorage.expires_at.isnot(None),
            TireStorage.expires_at <= edge).all()

        return sorted(rows, key=lambda row: row.expires_at)

    def fill_missing_deadlines(self, again=False):
        """
        Проставить срок комплектам, принятым до того, как срок появился.

        Без этого у всего, что уже лежит на складе, срока нет, и
        владельцам никто не напомнит.

        Делается ровно один раз, и это важно. Пустой срок значит две
        разных вещи: «срока ещё не было в программе» и «приняли
        бессрочно, потому что так настроено». Отличить их по строке
        нельзя, поэтому отличаем по времени: при первом запуске новой
        версии бессрочных быть не может — настройки ещё не было. Дальше
        пустой срок означает только намеренно бессрочное хранение, и
        трогать его нельзя.
        """
        from services.settings_service import SettingsService

        settings = SettingsService(self.db)
        if not again and settings.get_raw(self.FILLED_KEY) == '1':
            return 0

        settings.set(self.FILLED_KEY, '1')

        months = self.storage_months()
        if not months:
            return 0

        rows = self.db.query(TireStorage).filter(
            TireStorage.status == 'stored',
            TireStorage.expires_at.is_(None),
            TireStorage.accepted_date.isnot(None)).all()

        for row in rows:
            row.expires_at = self.deadline_for(row.accepted_date, months)

        if rows:
            self.db.commit()

        return len(rows)

    def accept_storage(self, car_number, driver_license, storage_type, diameter,
                       brand, damage, wear, comments='', wheel_type=None):
        """Принять комплект на хранение."""
        try:
            storage = TireStorage(
                car_number=normalize_plate(car_number),
                driver_license=driver_license,
                storage_type=storage_type,
                diameter=diameter,
                brand=brand,
                damage=damage,
                wear=wear,
                comments=comments,
                wheel_type=wheel_type,
                price=self.calculate_price(diameter),
                status='stored'
            )
            storage.expires_at = self.deadline_for(get_moscow_time())
            self.db.add(storage)
            self.db.commit()
            self.db.refresh(storage)
            return storage
        except Exception:
            self.db.rollback()
            raise

    def search_by_car_number(self, car_number):
        """
        Комплекты по номеру машины: и лежащие на хранении, и уже выданные.

        Номер ищется в любом написании.
        """
        return self.db.query(TireStorage).filter(
            TireStorage.car_number == normalize_plate(car_number)
        ).order_by(
            # 'stored' идёт после 'released' в алфавите, поэтому desc()
            TireStorage.status.desc(),
            TireStorage.accepted_date.desc()
        ).all()

    def release_storage(self, storage_id):
        """Выдать комплект владельцу."""
        try:
            storage = self.db.query(TireStorage).filter(
                TireStorage.id == storage_id
            ).first()
            if not storage:
                return None

            if storage.status == 'released':
                raise ValueError(
                    f"Комплект №{storage_id} уже выдан "
                    f"{storage.released_date.strftime('%d.%m.%Y') if storage.released_date else ''}"
                )

            storage.status = 'released'
            storage.released_date = get_moscow_time()
            self.db.commit()
            self.db.refresh(storage)

            from services.audit_service import AuditService
            AuditService(self.db).log(
                AuditService.STORAGE_RELEASE,
                f"Выдан комплект №{storage_id} ({storage.car_number}, "
                f"{storage.storage_type}, {storage.diameter})",
                entity_type='tire_storage', entity_id=storage_id
            )
            return storage
        except Exception:
            self.db.rollback()
            raise

    def get_all_stored(self):
        """Все комплекты: сначала лежащие на хранении, затем выданные."""
        return self.db.query(TireStorage).order_by(
            TireStorage.status.desc(),
            TireStorage.accepted_date.desc()
        ).all()

    def get_storage_by_id(self, storage_id):
        return self.db.query(TireStorage).filter(TireStorage.id == storage_id).first()
