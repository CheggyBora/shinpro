"""
Счёт за покраску дисков.

Приёмщику и клиенту нужно одно и то же: выбрал размер, отметил
дополнения — увидел цену. Поэтому счёт считается в одном месте, а не
дважды в двух интерфейсах: иначе программа и сайт однажды назовут
человеку разные суммы, и объясняться придётся мастеру.

Цены задаёт шиномонтаж. Те, что стоят по умолчанию, — чтобы
калькулятор работал с первого запуска, а не показывал нули; их надо
заменить своими.
"""
from models import PaintOption, Settings

# Базовая покраска за одно колесо. Чем больше диск, тем больше краски,
# дольше подготовка и дороже ошибка
DEFAULT_BASE_PRICES = {
    13: 3000, 14: 3000, 15: 3000,
    16: 3500, 17: 3500, 18: 3500,
    19: 4000, 20: 4000,
    21: 5000, 22: 5000, 23: 5000, 24: 5000,
}

# Дополнения, с которыми калькулятор заводится в первый раз.
# (название, цена, за колесо ли, пояснение)
#
# Только то, что делают с самим диском. Покраска суппортов или поводков
# дворника — отдельная работа: диски для неё снимать не надо, и считать
# её вперемешку с колёсами значит путать и себя, и клиента. Нужна в
# калькуляторе — добавляется руками, со счётом за заказ.
DEFAULT_OPTIONS = [
    ('Алмазная проточка', 2500, True,
     'Снимаем тонкий слой на станке — лицевая часть становится как новая'),
    ('Пескоструйная обработка', 1000, True,
     'Снимает старую краску и коррозию до чистого металла'),
    ('Косметический ремонт (напыление)', 1500, True,
     'Заделываем задиры и сколы от бордюров'),
    ('Покраска в два цвета', 1500, True,
     'Лицевая часть и основа разными цветами'),
    ('Цветной кант', 800, True, 'Контрастная полоса по краю диска'),
    ('Нанесение логотипа', 700, True, 'Логотип марки или свой рисунок'),
]

# Колёс в заказе по умолчанию
DEFAULT_WHEELS = 4


class PaintService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Цены
    # ------------------------------------------------------------------

    def base_price(self, diameter):
        """Базовая покраска одного колеса этого размера."""
        try:
            size = int(str(diameter).upper().replace('R', '').strip())
        except (TypeError, ValueError):
            return 0.0

        if size not in DEFAULT_BASE_PRICES:
            return 0.0

        row = self.db.query(Settings).filter(
            Settings.key == f'paint_price_r{size}').first()

        if row and row.value:
            try:
                return float(row.value)
            except ValueError:
                pass

        return float(DEFAULT_BASE_PRICES[size])

    def set_base_price(self, diameter, price):
        size = int(str(diameter).upper().replace('R', '').strip())
        key = f'paint_price_r{size}'

        row = self.db.query(Settings).filter(Settings.key == key).first()
        if row:
            row.value = str(float(price))
        else:
            self.db.add(Settings(key=key, value=str(float(price))))

        self.db.commit()

    def sizes(self):
        """Размеры с ценами, по возрастанию."""
        return [{'diameter': size, 'price': self.base_price(size)}
                for size in sorted(DEFAULT_BASE_PRICES)]

    # ------------------------------------------------------------------
    # Дополнения
    # ------------------------------------------------------------------

    def ensure_defaults(self):
        """
        Завести дополнения, если их ещё нет.

        Только когда список пуст: удалил человек ненужное — возвращать
        это при каждом запуске было бы издевательством.
        """
        if self.db.query(PaintOption).count():
            return 0

        for position, (name, price, per_wheel, note) in enumerate(
                DEFAULT_OPTIONS, start=1):
            self.db.add(PaintOption(name=name, price=float(price),
                                    per_wheel=per_wheel, note=note,
                                    position=position * 10, is_active=True))

        self.db.commit()
        return len(DEFAULT_OPTIONS)

    def options(self, only_active=True):
        query = self.db.query(PaintOption)
        if only_active:
            query = query.filter(PaintOption.is_active.is_(True))
        return query.order_by(PaintOption.position, PaintOption.id).all()

    def option(self, option_id):
        return self.db.query(PaintOption).filter(
            PaintOption.id == option_id).first()

    def save_option(self, option_id=None, **fields):
        row = self.option(option_id) if option_id else PaintOption()

        if row is None:
            return None

        for name in ('name', 'price', 'per_wheel', 'note', 'is_active',
                     'position'):
            if name in fields:
                setattr(row, name, fields[name])

        if option_id is None:
            self.db.add(row)

        self.db.commit()
        self.db.refresh(row)
        return row

    def remove_option(self, option_id):
        row = self.option(option_id)
        if row is None:
            return False

        self.db.delete(row)
        self.db.commit()
        return True

    # ------------------------------------------------------------------
    # Счёт
    # ------------------------------------------------------------------

    def quote(self, diameter, wheels=DEFAULT_WHEELS, option_ids=()):
        """
        Посчитать заказ. Возвращает строки счёта и итог.

        Строками, а не одним числом: человек должен видеть, из чего
        сложилась сумма. «Двадцать тысяч» без расшифровки звучит как
        выдумка, а та же сумма по строкам — как работа.
        """
        wheels = max(1, int(wheels or 1))
        base = self.base_price(diameter)

        lines = [{
            'name': f'Базовая покраска, R{diameter}',
            'price': base,
            'quantity': wheels,
            'total': round(base * wheels, 2),
            'per_wheel': True,
        }]

        picked = set(int(one) for one in option_ids or ())

        for row in self.options():
            if row.id not in picked:
                continue

            quantity = wheels if row.per_wheel else 1
            lines.append({
                'id': row.id,
                'name': row.name,
                'price': float(row.price or 0),
                'quantity': quantity,
                'total': round(float(row.price or 0) * quantity, 2),
                'per_wheel': bool(row.per_wheel),
            })

        total = round(sum(line['total'] for line in lines), 2)

        return {
            'diameter': diameter,
            'wheels': wheels,
            'lines': lines,
            'total': total,
        }

    def config(self):
        """
        Всё, что нужно калькулятору: размеры и дополнения.

        Этим же составом уезжает на сервер — чтобы кабинет клиента
        считал ровно так же, как приёмщик.
        """
        return {
            'sizes': self.sizes(),
            'wheels_default': DEFAULT_WHEELS,
            'options': [{
                'id': row.id,
                'name': row.name,
                'price': float(row.price or 0),
                'per_wheel': bool(row.per_wheel),
                'note': row.note,
            } for row in self.options()],
        }
