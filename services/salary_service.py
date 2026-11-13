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

    def _lines(self, order_id):
        """
        Строки наряда для зарплаты исполнителям: [(строка, название, база)].

        Товары шиномонтажа и мойки (вентили, химия) входят, только когда
        у направления база «от выручки»: тогда процент со всего. При базе
        «минус расходники» товар — расходник, с него не начисляется
        (решение владельца 13.11.2026). Магазин — не здесь (_shop).
        """
        from services import directions

        items = self.db.query(WorkOrderItem).filter(
            WorkOrderItem.work_order_id == order_id).order_by(WorkOrderItem.id).all()
        lines = []
        for item in items:
            direction = getattr(item, 'direction', None) or 'tire'
            if direction == directions.SHOP:
                continue
            if getattr(item, 'is_goods', False) and \
                    directions.salary_base(self.db, direction) != 'revenue':
                continue
            name = item.service.name if item.service else f'Позиция №{item.id}'
            lines.append((item, name, self._base(item)))
        return lines

    def _work_of(self, order_id):
        """
        Работы шиномонтажа, которые делят мастера наряда: [(название, база)].
        Без строк, отданных другим исполнителям, и без товаров: по ним
        мастера наряда не нужны.
        """
        return [(name, base) for item, name, base in self._lines(order_id)
                if (getattr(item, 'direction', None) or 'tire') == 'tire'
                and not getattr(item, 'is_goods', False)
                and not ids_of(getattr(item, 'employee_ids', None))]

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

    def _who(self, order, item):
        """
        Кто делал строку, если не мастера наряда по общему правилу:
        исполнители строки (их выбрали отдельно), у мойки — мойщики машины,
        а до них — тот, кто стоит в строке. None — строку делят мастера
        шиномонтажа наряда.
        """
        own = ids_of(getattr(item, 'employee_ids', None))
        if own:
            return own
        if (getattr(item, 'direction', None) or 'tire') == 'tire':
            return None
        washers = ids_of(getattr(order, 'wash_employee_ids', None))
        return washers or ([item.employee_id] if item.employee_id else [])

    def _wash_of(self, order_id):
        """Строки со своими исполнителями: [(название, база, [кто], направление)]."""
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        lines = []
        for item, name, base in self._lines(order_id):
            who = self._who(order, item)
            if who is None:
                continue
            lines.append((name, base, who, getattr(item, 'direction', None) or 'tire',
                          bool(getattr(item, 'is_goods', False))))
        return lines

    def unassigned_wash(self, order_id):
        """Услуги, у которых не выбрано, кто делал (товар без мойщика не держит)."""
        return [name for name, _base, who, _d, goods in self._wash_of(order_id)
                if not who and not goods]

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

    @staticmethod
    def _add(people, employee_id, amount, line):
        share = people.setdefault(employee_id, {'amount': 0.0, 'raw': 0.0, 'lines': [], 'skipped': []})
        share['raw'] = share.get('raw', share['amount']) + amount
        share['amount'] = round(share['raw'], 2)
        share['lines'].append(line)

    def distribute(self, order):
        """
        Кому сколько по наряду (решения владельца 26.10–13.11.2026).

        Шиномонтаж — делят мастера наряда, каждый по своему проценту ÷
        сколько их, с исключениями по категориям. Мойка — так же мойщики
        машины, только процент. Любую строку можно отдать другим
        исполнителям — тогда её делят они. Товары направления — только при
        базе «от выручки». Администратор — свой процент сверху, магазин —
        продавцу.
        """
        from services import directions

        employee_ids = ids_of(order.employee_ids)
        tire_work = self._work_of(order.id)
        people, nobody = split(tire_work, self._people_of(employee_ids)) \
            if employee_ids and tire_work else ({}, [{'name': n, 'base': round(b, 2)}
                                       for n, b in tire_work if b > 0])
        # Товары шиномонтажа при базе «от выручки» — мастерам наряда, без
        # исключений категорий: исключают работы, а не вентиль
        for item, name, base in self._lines(order.id):
            if (item.direction or 'tire') != 'tire' or not item.is_goods \
                    or ids_of(item.employee_ids) or base <= 0:
                continue
            if not employee_ids:
                nobody.append({'name': name, 'base': round(base, 2)})
                continue
            for employee_id, percent, _excluded in self._people_of(employee_ids):
                amount = base * percent / 100 / len(employee_ids)
                self._add(people, employee_id, amount, {
                    'name': name, 'base': round(base, 2), 'percent': percent,
                    'shared': len(employee_ids), 'amount': round(amount, 2), 'direction': 'tire'})

        for name, base, who, direction, _goods in self._wash_of(order.id):
            if not who:
                if base > 0:
                    nobody.append({'name': name, 'base': round(base, 2)})
                continue
            for employee_id in who:
                employee = self.db.query(Employee).filter(Employee.id == employee_id).first()
                # Мойка — по ставке мойки, шиномонтаж — по ставке шиномонтажа
                own = (employee.wash_percent if direction == directions.WASH
                       else employee.salary_percent) if employee is not None else None
                percent = own if own is not None else FALLBACK_PERCENT
                amount = base * percent / 100 / len(who)
                self._add(people, employee_id, amount, {
                    'name': name, 'base': round(base, 2), 'percent': percent,
                    'shared': len(who), 'amount': round(amount, 2), 'direction': direction})
        self._admins(order, people)
        self._shop(order, people)
        for share in people.values():
            share.pop('raw', None)
        return people, nobody

    def _shop(self, order, people):
        """
        С продаж магазина: процент с продаж включён — продавцу строки, по
        его ставке магазина. От суммы продажи или от наценки. У карточки
        задан бонус, ₽ — по этому товару вместо процента. Продал
        администратор, которому и так идёт его процент с магазина, —
        второй раз не получает (решение владельца 13.11.2026).
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
        shop_admin = self.order_admins(order).get(directions.SHOP) \
            if directions.admin_shop_on(self.db) else None
        for line in lines:
            seller = self.db.query(Employee).filter(Employee.id == line.employee_id).first()
            if seller is None:
                continue
            if shop_admin is not None and seller.id == shop_admin.id \
                    and float(shop_admin.admin_percent or 0) > 0:
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

    def order_admins(self, order):
        """
        Администратор наряда по направлениям: {'tire': Employee, ...}.
        Выбран в наряде (или пришёл с поста мойки) — он. Не выбран, а на
        смене один — он. Двое и больше и не выбран — None: выбирают.
        """
        chosen = admin_map(getattr(order, 'admin_ids', None))
        on_shift = self.admins_on_shift()
        result = {}
        for direction in ('tire', 'wash', 'shop'):
            employee_id = chosen.get(direction)
            if employee_id:
                result[direction] = self.db.query(Employee).filter(Employee.id == employee_id).first()
            elif len(on_shift) == 1:
                result[direction] = on_shift[0]
            else:
                result[direction] = None
        return result

    def missing_admins(self, order_id):
        """Направления наряда, где администраторов на смене несколько, а не выбран."""
        from services import directions
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if order is None or len(self.admins_on_shift()) < 2:
            return []
        have = {getattr(i, 'direction', None) or 'tire' for i in self.db.query(WorkOrderItem).filter(
            WorkOrderItem.work_order_id == order_id).all()}
        if not directions.admin_shop_on(self.db):
            have.discard(directions.SHOP)
        admins = self.order_admins(order)
        return [directions.TITLES[d] for d in ('tire', 'wash', 'shop') if d in have and admins.get(d) is None]

    def _admins(self, order, people):
        """
        Администратор — свой процент с выручки наряда, сверху, не из доли
        мастеров и мойщиков (решения владельца 08–13.11.2026).

        Кому: администратору наряда по направлению (order_admins) — один
        на смене или выбранный; пополам больше не делят.

        С чего: со всех услуг шиномонтажа и мойки, кроме исключённых в его
        категории. Товары направления — при базе «вся сумма» входят, при
        «за вычетом расходников» нет. Магазин — если включено «с продажи
        товаров», от суммы продажи.
        """
        from services import directions
        from services.employee_role_service import EmployeeRoleService
        from services.order_service import OrderService

        admins = self.order_admins(order)
        if not any(a is not None and float(a.admin_percent or 0) > 0 for a in admins.values()):
            return
        roles = EmployeeRoleService(self.db)
        items = self.db.query(WorkOrderItem).filter(
            WorkOrderItem.work_order_id == order.id).order_by(WorkOrderItem.id).all()
        minus = directions.admin_salary_base(self.db) == 'minus'
        shop_on = directions.admin_shop_on(self.db)
        # Строки до округлений — сводим к итогу наряда, как в отчётах
        lines_total = sum(OrderService.item_total(i) for i in items)
        order_total = float(order.total_amount or 0) or OrderService(self.db).calculate_total(order.id)
        scale = (order_total / lines_total) if lines_total else 0.0
        for item in items:
            direction = getattr(item, 'direction', None) or 'tire'
            admin = admins.get(direction)
            if admin is None or float(admin.admin_percent or 0) <= 0:
                continue
            goods = bool(getattr(item, 'is_goods', False))
            name = item.service.name if item.service else f'Позиция №{item.id}'
            base = OrderService.item_total(item)
            if direction == directions.SHOP:
                if not shop_on:
                    continue
            else:
                if goods and minus:
                    continue
                if minus:
                    base -= OrderService.item_consumables(item)
                role = roles.role_of(admin)
                if not goods and role is not None and name in role.excluded:
                    share = people.setdefault(admin.id, {'amount': 0.0, 'lines': [], 'skipped': []})
                    if name not in share['skipped']:
                        share['skipped'].append(name)
                    continue
            base = max(0.0, base * scale)
            if base <= 0:
                continue
            percent = float(admin.admin_percent or 0)
            self._add(people, admin.id, base * percent / 100, {
                'name': 'Администратор: ' + name, 'base': round(base, 2), 'percent': percent,
                'shared': 1, 'amount': round(base * percent / 100, 2), 'direction': direction})

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
        # Администраторов на смене несколько — процент получает выбранный
        missing_admin = self.missing_admins(order_id)
        if missing_admin:
            raise ValueError("Выберите администратора: " + ", ".join(missing_admin).lower())

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


def admin_map(value):
    """«tire:5,wash:6» → {'tire': 5, 'wash': 6}."""
    result = {}
    for part in str(value or '').split(','):
        key, _, number = part.partition(':')
        if key.strip() and number.strip().isdigit():
            result[key.strip()] = int(number)
    return result


def admin_join(mapping):
    return ','.join(f'{k}:{v}' for k, v in mapping.items() if v) or None
