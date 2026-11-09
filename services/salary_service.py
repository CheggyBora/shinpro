import json

from models import WorkOrder, WorkOrderItem, SalaryTransaction, Employee
from sqlalchemy.orm import Session
from utils import get_moscow_time

# Процент тому, кого нет в базе сотрудников. Так было и раньше:
# наряд оплачивается, а не падает из-за удалённой записи
FALLBACK_PERCENT = 40.0


def split(work, people):
    """
    Разложить зарплату по услугам наряда.

    Каждая услуга считается отдельно: её делят только те из наряда,
    кому она начисляется по категории. Доля каждого —

        база услуги × его процент ÷ сколько человек её делят.

    Процент у каждого свой, делитель общий: доля одного не зависит от
    процента соседа. Съёмщик без права на правку не уменьшает долю
    мастера за правку — мастер её делил бы с ним, а делает один.

    Если у всех в наряде исключений нет, выходит ровно то, что
    начислялось раньше: база всего наряда × процент ÷ число людей.
    Для этого округляем итог человека, а не каждую строку: иначе
    копейки разъезжались бы со старым расчётом.

    work   — [(название услуги, база)], база уже без скидок и расходников;
             товаров тут нет — с них не начисляется никому.
    people — [(employee_id, процент, множество исключённых названий)].

    Возвращает (по людям, некому начислить):
        {employee_id: {'amount': 846.67,
                       'lines': [{'name', 'base', 'percent',
                                  'shared', 'amount'}],
                       'skipped': ['Правка литого диска']}},
        [{'name': 'Правка литого диска', 'base': 1500.0}]
    """
    result = {emp_id: {'raw': 0.0, 'lines': [], 'skipped': []}
              for emp_id, _, _ in people}
    nobody = []

    for name, base in work:
        takers = [(emp_id, percent) for emp_id, percent, excluded in people
                  if name not in excluded]
        for emp_id, _, excluded in people:
            if name in excluded and name not in result[emp_id]['skipped']:
                result[emp_id]['skipped'].append(name)

        if not takers:
            # На смене нет никого, кому эта услуга начисляется. Ошибки
            # тут нет — доля остаётся цеху, а в разборе это видно
            if base > 0:
                nobody.append({'name': name, 'base': round(base, 2)})
            continue

        shared = len(takers)
        for emp_id, percent in takers:
            amount = base * percent / 100 / shared
            result[emp_id]['raw'] += amount
            result[emp_id]['lines'].append({
                'name': name, 'base': round(base, 2), 'percent': percent,
                'shared': shared, 'amount': round(amount, 2)})

    people_result = {}
    for emp_id, data in result.items():
        people_result[emp_id] = {'amount': round(data['raw'], 2),
                                 'lines': data['lines'],
                                 'skipped': data['skipped']}
    return people_result, nobody


class SalaryService:
    def __init__(self, db: Session):
        self.db = db

    def _work_of(self, order_id):
        """
        Работы наряда для зарплаты: [(название, база)].

        База — стоимость позиции со всеми скидками минус расходники. Не
        ниже нуля: если материалы вышли дороже работы, мастер не уходит
        в минус. Товары не входят: вентиль мастер не делал, он достал
        его с полки.
        """
        from services.order_service import OrderService

        items = self.db.query(WorkOrderItem).filter(
            WorkOrderItem.work_order_id == order_id).order_by(
                WorkOrderItem.id).all()

        work = []
        for item in items:
            if getattr(item, 'is_goods', False):
                continue
            # Назначенное считается отдельно — тому, кто делал (distribute)
            if self._is_assigned(item):
                continue
            base = self._base(item)
            name = item.service.name if item.service else f'Позиция №{item.id}'
            work.append((name, base))
        return work

    def _base(self, item):
        """
        База строки для зарплаты. «От выручки» — итог строки после всех
        скидок; «минус расходники» — то же минус расходник строки. Что
        выбрано — своё у шиномонтажа и у мойки (docs/stock.md). Не ниже
        нуля: материалы дороже работы — мастер в минус не уходит.
        """
        from services.order_service import OrderService
        from services import directions
        total = OrderService.item_total(item)
        if directions.salary_base(self.db, getattr(item, 'direction', None) or 'tire') == 'revenue':
            return max(0.0, total)
        return max(0.0, total - OrderService.item_consumables(item))

    def _is_assigned(self, item):
        """Строку начисляют тому, кого выбрали: мойка — всегда, шиномонтаж —
        когда включён тумблер «назначать сотрудников и на шиномонтаж»."""
        from services import directions
        return directions.assigned(self.db, getattr(item, 'direction', None) or 'tire')

    def _wash_of(self, order_id):
        """
        Назначаемые строки: [(название, база, [кто делал], направление)].

        Кто делал — мойщики машины, выбранные в наряде (решение владельца
        09.11.2026). Не выбраны — тот, кто стоит в строке: так считались
        наряды до этого, и так же — когда на смене один человек.
        """
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        washers = ids_of(getattr(order, 'wash_employee_ids', None)) if order is not None else []
        items = self.db.query(WorkOrderItem).filter(
            WorkOrderItem.work_order_id == order_id).order_by(WorkOrderItem.id).all()
        lines = []
        for item in items:
            if getattr(item, 'is_goods', False) or not self._is_assigned(item):
                continue
            base = self._base(item)
            name = item.service.name if item.service else f'Позиция №{item.id}'
            who = washers or ([item.employee_id] if item.employee_id else [])
            lines.append((name, base, who, getattr(item, 'direction', None) or 'tire'))
        return lines

    def unassigned_wash(self, order_id):
        """Назначаемые услуги, у которых не выбрано, кто делал."""
        return [name for name, _base, who, _d in self._wash_of(order_id) if not who]

    def unsold_shop(self, order_id):
        """Товары магазина без продавца — когда процент с продаж включён."""
        from services import directions
        if not directions.shop_pay_on(self.db):
            return []
        return [i.service.name if i.service else f'Позиция №{i.id}'
                for i in self.db.query(WorkOrderItem).filter(
                    WorkOrderItem.work_order_id == order_id,
                    WorkOrderItem.direction == directions.SHOP).all()
                if not i.employee_id]

    def distribute(self, order):
        """
        Кому сколько по наряду. Шиномонтаж — как всегда: делят мастера,
        бывшие на смене при создании, по проценту шиномонтажа. Мойка —
        так же (решение владельца 09.11.2026): делят мойщики машины, каждый
        по своему проценту мойки ÷ сколько их. Исключений у мойщиков нет —
        только процент.
        """
        employee_ids = [int(i.strip()) for i in (order.employee_ids or '').split(',')
                        if i.strip()]
        tire_work = self._work_of(order.id)
        people, nobody = split(tire_work, self._people_of(employee_ids)) \
            if employee_ids and tire_work else ({}, [{'name': n, 'base': round(b, 2)}
                                       for n, b in tire_work if b > 0])
        for name, base, who, direction in self._wash_of(order.id):
            if not who:
                if base > 0:
                    nobody.append({'name': name, 'base': round(base, 2)})
                continue
            for employee_id in who:
                employee = self.db.query(Employee).filter(Employee.id == employee_id).first()
                # Мойка — по ставке мойки, шиномонтаж — по ставке шиномонтажа
                own = (employee.wash_percent if direction == 'wash' else employee.salary_percent) \
                    if employee is not None else None
                percent = own if own is not None else FALLBACK_PERCENT
                amount = base * percent / 100 / len(who)
                share = people.setdefault(employee_id, {'amount': 0.0, 'raw': 0.0,
                                                        'lines': [], 'skipped': []})
                share['raw'] = share.get('raw', share['amount']) + amount
                share['amount'] = round(share['raw'], 2)
                share['lines'].append({'name': name, 'base': round(base, 2), 'percent': percent,
                                       'shared': len(who), 'amount': round(amount, 2),
                                       'direction': direction})
        self._admins(order, people)
        self._shop(order, people)
        for share in people.values():
            share.pop('raw', None)
        return people, nobody

    def _shop(self, order, people):
        """
        С продаж магазина (решение владельца 09.11.2026): процент с продаж
        включён — продавцу строки, по его ставке магазина. Продаёт один
        человек — один и получает, администратор тоже только когда продал
        сам. От суммы продажи или от наценки. У карточки задан бонус, ₽ —
        по этому товару вместо процента.
        """
        from models.stock import StockItem
        from services import directions
        from services.order_service import OrderService

        if not directions.shop_pay_on(self.db):
            return
        lines = [i for i in self.db.query(WorkOrderItem).filter(
            WorkOrderItem.work_order_id == order.id).all()
            if (getattr(i, 'direction', None) or 'tire') == directions.SHOP and i.employee_id]
        margin = directions.shop_salary_base(self.db) == 'margin'
        for line in lines:
            seller = self.db.query(Employee).filter(Employee.id == line.employee_id).first()
            if seller is None:
                continue
            base = OrderService.item_total(line)
            if margin:
                base -= OrderService.item_consumables(line)
            base = max(0.0, base)
            card = self.db.query(StockItem).filter(StockItem.service_id == line.service_id).first()
            bonus = card.bonus if card is not None and card.bonus else None
            percent = float(seller.shop_percent or 0)
            amount = bonus * (line.quantity or 1) if bonus else base * percent / 100
            if amount <= 0:
                continue
            name = line.service.name if line.service else f'Позиция №{line.id}'
            share = people.setdefault(seller.id, {'amount': 0.0, 'lines': [], 'skipped': []})
            share['amount'] = round(share['amount'] + amount, 2)
            share['lines'].append({'name': 'Магазин: ' + name, 'base': round(base, 2),
                                   'percent': None if bonus else percent, 'bonus': bonus,
                                   'shared': 1, 'amount': round(amount, 2),
                                   'direction': directions.SHOP})

    def admins_on_shift(self):
        """Администраторы, отметившиеся на смене, — по одному разу."""
        from models import WorkShift
        from services.employee_role_service import EmployeeRoleService

        roles = EmployeeRoleService(self.db)
        admins = []
        for shift in self.db.query(WorkShift).filter(WorkShift.end_time.is_(None)).all():
            employee = shift.employee
            if employee is not None and roles.is_admin(employee) \
                    and employee.id not in [a.id for a in admins]:
                admins.append(employee)
        return admins

    def _admins(self, order, people):
        """
        Администраторы на смене — свой процент с выручки наряда, с
        шиномонтажа и с мойки (решения владельца 08–09.11.2026). Сверху,
        не из доли мастеров и мойщиков.

        С каких строк — по категории «Администратор», методом исключения:
        со всех услуг, кроме отмеченных. С товаров шиномонтажа и мойки не
        получает никто — ни мастера, ни администратор (решение владельца
        09.11.2026). Магазин — не здесь: с продажи получает только продавец.

        Двое на смене — каждую строку делят те, кому она начисляется,
        поровну: как мастера шиномонтаж. База — вся сумма строки или она
        же без расходников (Настройки → «От чего считается зарплата»).
        """
        from services import directions
        from services.employee_role_service import EmployeeRoleService
        from services.order_service import OrderService

        admins = self.admins_on_shift()
        admins = [a for a in admins if float(a.admin_percent or 0) > 0]
        if not admins:
            return
        roles = EmployeeRoleService(self.db)
        rules = {}
        for admin in admins:
            role = roles.role_of(admin)
            rules[admin.id] = role.excluded if role else set()

        items = self.db.query(WorkOrderItem).filter(
            WorkOrderItem.work_order_id == order.id).order_by(WorkOrderItem.id).all()
        minus = directions.admin_salary_base(self.db) == 'minus'
        # Строки до округлений — сводим к итогу наряда, как в отчётах.
        # Доля считается от всех строк: итог наряда включает и магазин
        lines_total = sum(OrderService.item_total(i) for i in items)
        order_total = float(order.total_amount or 0) or OrderService(self.db).calculate_total(order.id)
        scale = (order_total / lines_total) if lines_total else 0.0
        raw = {}
        for item in items:
            direction = getattr(item, 'direction', None) or 'tire'
            if direction == directions.SHOP:
                continue
            if getattr(item, 'is_goods', False):
                continue
            name = item.service.name if item.service else f'Позиция №{item.id}'
            base = OrderService.item_total(item)
            if minus:
                base -= OrderService.item_consumables(item)
            base = max(0.0, base * scale)
            if base <= 0:
                continue
            takers = [admin for admin in admins if name not in rules[admin.id]]
            for admin in admins:
                if admin not in takers:
                    share = people.setdefault(admin.id, {'amount': 0.0, 'lines': [], 'skipped': []})
                    if name not in share['skipped']:
                        share['skipped'].append(name)
            for admin in takers:
                percent = float(admin.admin_percent or 0)
                amount = base * percent / 100 / len(takers)
                share = people.setdefault(admin.id, {'amount': 0.0, 'lines': [], 'skipped': []})
                raw[admin.id] = raw.get(admin.id, 0.0) + amount
                share['lines'].append({'name': 'Администратор: ' + name, 'base': round(base, 2),
                                       'percent': percent, 'shared': len(takers),
                                       'amount': round(amount, 2), 'direction': direction})
        for admin_id, amount in raw.items():
            people[admin_id]['amount'] = round(people[admin_id]['amount'] + amount, 2)

    def _people_of(self, employee_ids):
        """[(employee_id, процент, исключённые услуги)] по наряду."""
        from services.employee_role_service import EmployeeRoleService

        roles = EmployeeRoleService(self.db)
        people = []
        for employee_id in employee_ids:
            employee = self.db.query(Employee).filter(
                Employee.id == employee_id).first()
            percent = (employee.salary_percent
                       if employee and employee.salary_percent is not None
                       else FALLBACK_PERCENT)
            role = roles.role_of(employee)
            people.append((employee_id, percent,
                           role.excluded if role else set()))
        return people

    def preview(self, order_id: int):
        """Посчитать, ничего не записывая: кому сколько и что некому."""
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if not order:
            return {}, []
        return self.distribute(order)

    def process_payment(self, order_id: int, payment_method: str, total_amount: float,
                        cash_amount: float = None):
        """
        Провести оплату и начислить зарплату.

        payment_method — cash, card или mixed: раздельно, тогда
        cash_amount — сколько наличными, остальное картой.

        Возвращает список услуг, которые некому было начислить, —
        [{'name', 'base'}]. Пустой — всё разошлось по людям.
        """
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if not order:
            raise ValueError("Наряд не найден")

        # Защита от повторной оплаты: если наряд уже оплачен, второй раз
        # начислять зарплату нельзя. Иначе при ошибке печати чека кассир
        # нажимал "Оплатить" ещё раз и ЗП начислялась дважды.
        if order.status == 'paid':
            raise ValueError(
                f"Наряд №{order_id} уже оплачен "
                f"({order.total_amount:.2f} руб.). Повторная оплата невозможна."
            )

        from models import PAY_CASH, PAY_CARD, PAY_MIXED
        if payment_method not in (PAY_CASH, PAY_CARD, PAY_MIXED):
            raise ValueError("Неизвестный способ оплаты")
        if payment_method == PAY_MIXED:
            cash_amount = round(float(cash_amount or 0), 2)
            if not 0 < cash_amount < round(total_amount, 2):
                raise ValueError(
                    f"Наличными — больше нуля и меньше {total_amount:.2f} руб.: "
                    f"остаток пойдёт картой")
        else:
            cash_amount = None

        # Мойка начисляется тому, кто её делал, — пока не выбрали, пробить
        # нельзя: зарплату было бы некому начислить
        missing = self.unassigned_wash(order_id)
        if missing:
            raise ValueError("Выберите, кто делал: " + ", ".join(missing))
        # Процент с продаж включён — продавец обязателен: иначе процент
        # некому, а продавал же кто-то
        unsold = self.unsold_shop(order_id)
        if unsold:
            raise ValueError("Выберите, кто продал: " + ", ".join(unsold))

        # Используем сохранённых сотрудников из наряда. Наряд только мойки
        # обходится без них — там каждая строка со своим сотрудником
        if not order.employee_ids and self._work_of(order_id):
            raise ValueError("Нет сотрудников в наряде")

        employee_ids = [int(id.strip()) for id in (order.employee_ids or '').split(',')
                        if id.strip()]

        # Зарплата считается по каждой услуге отдельно, от её стоимости
        # минус расходники. Раньше база была одна на весь наряд — «итог
        # минус себестоимость», и у товара себестоимостью шла закупка:
        # наценка с вентиля попадала мастеру в процент, хотя с товаров
        # решили не начислять
        people, nobody = self.distribute(order)

        # Наряд только мойки: мастерам смены начислять нечего, строки —
        # только тем, кто мыл
        if not self._work_of(order_id):
            employee_ids = []
        for employee_id in list(dict.fromkeys(employee_ids + list(people))):
            share = people.get(employee_id, {'amount': 0.0, 'lines': [], 'skipped': []})
            transaction = SalaryTransaction(
                employee_id=employee_id,
                work_order_id=order_id,
                amount=share['amount'],
                detail=json.dumps({'lines': share['lines'],
                                   'skipped': share['skipped']},
                                  ensure_ascii=False),
            )
            self.db.add(transaction)

        from services.order_service import OrderService
        order_service = OrderService(self.db)

        # Наряд проводится тем днём, когда машину закрыли: открыли вчера,
        # пробили сегодня — выручка и зарплата в сегодняшней смене, а не
        # во вчерашней, по которой сводка уже ушла. Мастера — те же, кто
        # был при создании: их не трогаем
        from services.shift_service import ShiftService
        current = ShiftService(self.db).get_current_shift()
        if current is not None:
            order.shift_id = current.id

        order.paid_at = get_moscow_time()
        order.payment_method = payment_method
        order.cash_amount = cash_amount
        order.total_amount = total_amount
        order.consumables_amount = order_service.calculate_consumables(order_id)
        order.salary_base = order_service.calculate_salary_base(order_id)
        order.status = 'paid'

        self.db.commit()

        # Склад включён — списать материалы по услугам и проданные товары
        try:
            from services.stock_service import StockService
            StockService(self.db).write_off_order(order_id)
        except Exception as e:
            self.db.rollback()
            from logger import log
            log.error(f"Склад не списался по наряду №{order_id}: {e}")

        # Оплачен — машина ушла с поста: место в живой очереди закрыто,
        # пост свободен для следующего
        from services.live_queue_service import LiveQueueService
        LiveQueueService(self.db).order_closed(order_id)

        # Владелец смотрит в дашборд сразу после оплаты, и ждать
        # десять минут ему незачем
        from services import sync_nudge

        sync_nudge.request('наряд оплачен')

        return nobody


def wash_share(transaction):
    """Какая доля начисления — за мойку, по строкам разбора. None — разбора нет."""
    shares = direction_shares(transaction)
    return None if shares is None else shares.get('wash', 0.0)


def direction_shares(transaction):
    """Доли начисления по направлениям: {'tire': 0.6, 'wash': 0.3, 'shop': 0.1}."""
    detail = read_detail(transaction) or {}
    lines = detail.get('lines') or []
    total = sum(l.get('amount') or 0 for l in lines)
    if not total:
        return None
    shares = {}
    for line in lines:
        key = line.get('direction') or 'tire'
        shares[key] = shares.get(key, 0.0) + (line.get('amount') or 0) / total
    return shares


def by_direction(transactions):
    """
    Начисления наряда по людям и направлениям:
    [(transaction, {'tire': 380.0, 'wash': 360.0})].

    Дашборд мойки показывает зарплату отдельно (docs/wash_dashboard.md).
    Откат при возврате — отдельная строка без разбора: её делим в той же
    доле, что исходное начисление этого человека.
    """
    own = {}
    for row in transactions:
        shares = direction_shares(row)
        if shares is not None and (row.amount or 0) > 0:
            own.setdefault(row.employee_id, shares)
    result = []
    for row in transactions:
        amount = round(row.amount or 0.0, 2)
        shares = direction_shares(row)
        if shares is None:
            shares = own.get(row.employee_id) or {'tire': 1.0}
        result.append((row, _split(amount, shares)))
    return result


def _split(amount, shares):
    """
    Разделить сумму по долям направлений. Остаток от округлений — в
    шиномонтаж (или в первое направление), чтобы части сходились с суммой.
    """
    parts = {}
    for key in ('wash', 'shop'):
        if shares.get(key):
            part = round(amount * shares[key], 2)
            if part:
                parts[key] = part
    rest = round(amount - sum(parts.values()), 2)
    if rest or not parts:
        parts['tire'] = round(parts.get('tire', 0.0) + rest, 2)
    return parts


def read_detail(transaction):
    """Разбор начисления: {'lines': [...], 'skipped': [...]} или None."""
    raw = getattr(transaction, 'detail', None)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def ids_of(value):
    """«3,5» → [3, 5] — без пустых и повторов."""
    result = []
    for part in str(value or '').split(','):
        part = part.strip()
        if part.isdigit() and int(part) not in result:
            result.append(int(part))
    return result
