"""
Работы у партнёров (решения владельца 13.11.2026, docs/partners.md).

Сварка диска, покраска, заказ шин — делает контрагент. Мы берём с
клиента свою цену (она в наряде и чеке), партнёру отдаём его цену
(она только в задаче и отчётах), разница — наша маржа.

Работа — это задача календаря с полями партнёра: так она живёт и в
цеху, и на сервере, видна в дашборде и в кабинете сотрудника. Строка
в наряде ссылается на неё (WorkOrderItem.partner_task_uid). Работу
создают из наряда или отдельно — тогда наряд заводится сам: деньги
клиента всегда идут через наряд.

Статусы:
    agree     согласование с партнёром — ждём его цену
    client    согласование с клиентом — покраска и шины: цену партнёра
              знаем, клиент ещё не сказал «да»
    work      в работе у партнёра
    wait_pay  закрыто, ждёт оплаты партнёру
    paid      оплачено
    refused   отказ (партнёр не взялся или клиент передумал)

Оплата партнёру: наличные из кассы — РКО; безнал с расчётного счёта —
расходный ордер по безналу, касса не меняется; другое — нигде не
учитывается, только пометка.

Зарплата с работы — по её правилу: кому (никому, тому, кто оформил,
выбранным) и как (вся маржа, % от нашей цены, % от маржи, ₽). Мастерам
наряда с работы партнёра ничего: делали не они. Администратор получает
свой процент с полной цены, как с остальных услуг.
"""
from datetime import date

from models import (CalendarTask, Counterparty, PartnerOffering, Service, WorkOrder,
                    WorkOrderItem, SalaryTransaction)
from models.calendar import WORK, PAINT, TIRES, SOURCE_SHOP, new_uid
from utils import get_moscow_time

KIND_WORK, KIND_PAINT, KIND_TIRES = 'work', 'paint', 'tires'
KIND_TITLES = {KIND_WORK: 'Работа', KIND_PAINT: 'Покраска', KIND_TIRES: 'Заказ шин'}
KIND_CATEGORY = {KIND_WORK: WORK, KIND_PAINT: PAINT, KIND_TIRES: TIRES}

ST_AGREE, ST_CLIENT, ST_WORK, ST_WAIT, ST_PAID, ST_REFUSED = (
    'agree', 'client', 'work', 'wait_pay', 'paid', 'refused')
STATUS_TITLES = {
    ST_AGREE: 'Согласование с партнёром',
    ST_CLIENT: 'Согласование с клиентом',
    ST_WORK: 'В работе у партнёра',
    ST_WAIT: 'Закрыто — ждёт оплаты',
    ST_PAID: 'Оплачено',
    ST_REFUSED: 'Отказ',
}
# Цвета статусов (текст, фон) — как в макете
STATUS_COLORS = {
    ST_AGREE: ('#92400e', '#fef3c7'), ST_CLIENT: ('#92400e', '#fef3c7'),
    ST_WORK: ('#1e40af', '#dbeafe'), ST_WAIT: ('#9a3412', '#ffedd5'),
    ST_PAID: ('#065f46', '#d1fae5'), ST_REFUSED: ('#475569', '#e2e8f0'),
}

SAL_NONE, SAL_CREATOR, SAL_PEOPLE = 'none', 'creator', 'people'
SALARY_TO_TITLES = {SAL_NONE: 'никому', SAL_CREATOR: 'тому, кто оформил', SAL_PEOPLE: 'выбранным'}
MODE_MARGIN_ALL, MODE_PRICE_PCT, MODE_MARGIN_PCT, MODE_FIXED = (
    'margin_all', 'price_pct', 'margin_pct', 'fixed')
MODE_TITLES = {MODE_MARGIN_ALL: 'вся маржа', MODE_PRICE_PCT: '% от нашей цены',
               MODE_MARGIN_PCT: '% от маржи', MODE_FIXED: 'фикс, ₽'}

PAY_CASH, PAY_NONCASH, PAY_OTHER = 'cash', 'noncash', 'other'
PAY_TITLES = {PAY_CASH: 'наличные из кассы (РКО)', PAY_NONCASH: 'безнал с расчётного счёта',
              PAY_OTHER: 'другое'}
CASH_CATEGORY = 'Партнёры'
# Работа без машины — наряд на эту «машину»
NO_PLATE = 'ПАРТНЁР'


class PartnerError(ValueError):
    pass


def _money(value, field='Цена'):
    if value in (None, ''):
        return None
    try:
        number = round(float(str(value).replace(',', '.').replace(' ', '').replace('₽', '')), 2)
    except ValueError:
        raise PartnerError(f'{field} — числом, например 2000')
    if number < 0:
        raise PartnerError(f'{field} не может быть меньше нуля')
    return number


def _ids(value):
    from services.salary_service import ids_of
    return ids_of(value)


def number_of(task):
    return f'П-{task.id}'


class PartnerService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Постоянные услуги контрагента
    # ------------------------------------------------------------------

    def offerings(self, counterparty_uid):
        return self.db.query(PartnerOffering).filter(
            PartnerOffering.counterparty_uid == counterparty_uid,
            PartnerOffering.deleted.is_(False)).order_by(PartnerOffering.name).all()

    def offering(self, uid):
        return self.db.query(PartnerOffering).filter(PartnerOffering.uid == uid).first() if uid else None

    def save_offering(self, offering=None, **fields):
        name = (fields.get('name', offering.name if offering else '') or '').strip()
        if not name:
            raise PartnerError('Напишите название услуги')
        if offering is None:
            party = fields.get('counterparty_uid')
            if not self.db.query(Counterparty).filter(Counterparty.uid == party).first():
                raise PartnerError('Контрагент не найден')
            offering = PartnerOffering(uid=new_uid(), counterparty_uid=party, name=name)
            self.db.add(offering)
        offering.name = name[:200]
        if 'kind' in fields:
            offering.kind = fields['kind'] if fields['kind'] in KIND_TITLES else KIND_WORK
        if 'our_price' in fields:
            offering.our_price = _money(fields['our_price'], 'Наша цена')
        if 'partner_price' in fields:
            offering.partner_price = _money(fields['partner_price'], 'Цена партнёра')
        self._apply_salary(offering, fields)
        offering.updated_at = get_moscow_time()
        self.db.commit()
        return offering

    def delete_offering(self, offering):
        offering.deleted = True
        offering.updated_at = get_moscow_time()
        self.db.commit()

    @staticmethod
    def _apply_salary(row, fields):
        """Правило зарплаты: кому, как, сколько, кому именно."""
        if 'salary_to' in fields:
            row.salary_to = fields['salary_to'] if fields['salary_to'] in SALARY_TO_TITLES else SAL_NONE
        if 'salary_mode' in fields:
            row.salary_mode = fields['salary_mode'] if fields['salary_mode'] in MODE_TITLES else None
        if 'salary_value' in fields:
            row.salary_value = _money(fields['salary_value'], 'Сколько')
        if 'salary_people' in fields:
            people = fields['salary_people']
            if isinstance(people, (list, tuple)):
                people = ','.join(str(int(p)) for p in people if p)
            row.salary_people = people or None
        if (row.salary_to or SAL_NONE) != SAL_NONE:
            if not row.salary_mode:
                raise PartnerError('Выберите, как начислять: вся маржа, % от цены, % от маржи или ₽')
            if row.salary_mode != MODE_MARGIN_ALL and not row.salary_value:
                raise PartnerError('Укажите, сколько начислять')
            if row.salary_to == SAL_PEOPLE and not _ids(row.salary_people):
                raise PartnerError('Отметьте, кому начислять')

    # ------------------------------------------------------------------
    # Работы
    # ------------------------------------------------------------------

    def job(self, uid):
        return self.db.query(CalendarTask).filter(CalendarTask.uid == uid).first() if uid else None

    def jobs(self, statuses=None, counterparty_uid=None, order_id=None):
        query = self.db.query(CalendarTask).filter(CalendarTask.partner_kind.isnot(None),
                                                   CalendarTask.deleted.is_(False))
        if statuses:
            query = query.filter(CalendarTask.partner_status.in_(list(statuses)))
        if counterparty_uid:
            query = query.filter(CalendarTask.counterparty_uid == counterparty_uid)
        if order_id:
            query = query.filter(CalendarTask.order_id == order_id)
        return query.order_by(CalendarTask.id).all()

    def to_pay(self):
        """Оплата партнёрам: закрытые работы, которые ждут денег."""
        return self.jobs(statuses=[ST_WAIT])

    def create_job(self, counterparty_uid, name, our_price, partner_price=None, kind=KIND_WORK,
                   order_id=None, plate=None, client_name=None, client_phone=None,
                   salary=None, creator_id=None, due_date=None, note=None, needs_client=None,
                   created_by=None):
        """
        Оформить работу у партнёра. Из наряда — order_id; отдельно — наряд
        заведётся сам на номер машины (или «ПАРТНЁР», если машины нет).
        Цена партнёра известна (договорились по телефону) — сразу в работу;
        у покраски и шин ещё нужно «да» клиента.
        """
        from services.calendar_service import CalendarService
        from services.order_service import OrderService

        party = self.db.query(Counterparty).filter(Counterparty.uid == counterparty_uid).first()
        if party is None or party.deleted:
            raise PartnerError('Выберите партнёра')
        name = (name or '').strip()
        if not name:
            raise PartnerError('Напишите, что за работа')
        our_price = _money(our_price, 'Цена клиенту')
        if not our_price:
            raise PartnerError('Укажите цену клиенту')
        partner_price = _money(partner_price, 'Цена партнёра')
        kind = kind if kind in KIND_TITLES else KIND_WORK
        if needs_client is None:
            needs_client = kind in (KIND_PAINT, KIND_TIRES)

        orders = OrderService(self.db)
        if order_id:
            order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
            if order is None:
                raise PartnerError('Наряд не найден')
            if order.status == 'paid':
                raise PartnerError('Наряд уже оплачен — оформите работу отдельно')
        else:
            order = orders.create_order(plate or NO_PLATE, '', 'car', client_name=client_name,
                                        client_phone=client_phone,
                                        create_client=bool(client_name or client_phone),
                                        directions=[party.direction or 'tire'])
        from services import directions as _directions
        have = _directions.parse(order.directions)
        line_direction = party.direction if party.direction in have else have[0]

        status = ST_AGREE
        if partner_price is not None:
            status = ST_CLIENT if needs_client else ST_WORK

        plate_shown = order.car.license_plate if order.car else (plate or '')
        task = CalendarService(self.db).create(
            title=f'{name} · {plate_shown}'.strip(' ·'), due_date=due_date or date.today(),
            category=KIND_CATEGORY[kind], direction=party.direction or 'tire', note=note,
            license_plate=plate_shown if plate_shown != NO_PLATE else None,
            client_name=client_name, client_phone=client_phone,
            counterparty_uid=party.uid, amount=our_price, source=SOURCE_SHOP,
            created_by=created_by)
        task.partner_kind = kind
        task.partner_status = status
        task.our_price = our_price
        task.partner_price = partner_price
        task.order_id = order.id
        task.creator_id = creator_id
        task.needs_client = bool(needs_client)
        self._apply_salary(task, dict(salary or {}))
        task.salary_to = task.salary_to or SAL_NONE

        service = Service(name=name[:200], vehicle_type='all', flat_price=our_price,
                          direction=line_direction, is_active=False, is_partner=True,
                          editable_price=True)
        self.db.add(service)
        self.db.commit()
        item = orders.add_service_to_order(order.id, service.id)
        item.price = our_price
        item.partner_task_uid = task.uid
        self._touch(task)
        return task

    @staticmethod
    def needs_client(task):
        if task.needs_client is not None:
            return bool(task.needs_client)
        return task.partner_kind in (KIND_PAINT, KIND_TIRES)

    def _touch(self, task):
        from services.calendar_service import _later, CalendarService
        task.updated_at = _later(task.updated_at)
        self.db.commit()
        CalendarService(self.db)._changed()

    def line_of(self, task):
        return self.db.query(WorkOrderItem).filter(WorkOrderItem.partner_task_uid == task.uid).first()

    def order_of(self, task):
        return self.db.query(WorkOrder).filter(WorkOrder.id == task.order_id).first() \
            if task.order_id else None

    def set_partner_price(self, task, price):
        """Цена партнёра — из чата или вписали руками. Менять можно до оплаты."""
        if task.partner_status == ST_PAID:
            raise PartnerError('Партнёру уже заплатили — цену не меняем')
        task.partner_price = _money(price, 'Цена партнёра')
        if task.partner_status == ST_AGREE and task.partner_price is not None:
            task.partner_status = ST_CLIENT if self.needs_client(task) else ST_WORK
        self._touch(task)
        self.settle_late(task)
        return task

    def set_our_price(self, task, price):
        """Цену клиенту поправили до оплаты наряда — и в строке наряда."""
        order = self.order_of(task)
        if order is not None and order.status == 'paid':
            raise PartnerError('Наряд уже оплачен — цену клиенту не меняем')
        price = _money(price, 'Цена клиенту')
        if not price:
            raise PartnerError('Укажите цену клиенту')
        task.our_price = task.amount = price
        line = self.line_of(task)
        if line is not None:
            line.price = price
        self._touch(task)
        return task

    def client_answer(self, task, yes):
        """Клиент согласился с ценой — в работу; отказался — работы нет."""
        if yes:
            task.partner_status = ST_WORK
            self._touch(task)
            return task
        return self.refuse(task, 'клиент отказался')

    def refuse(self, task, why=None):
        """Отказ: строку из неоплаченного наряда убираем, задача закрыта."""
        order = self.order_of(task)
        line = self.line_of(task)
        if order is not None and order.status != 'paid' and line is not None:
            self.db.delete(line)
        task.partner_status = ST_REFUSED
        if why:
            task.note = ((task.note or '') + f'\nОтказ: {why}').strip()
        task.done_at = get_moscow_time()
        self._touch(task)
        return task

    def finish(self, task, by=None):
        """Партнёр сделал — закрыто, ждёт оплаты."""
        if task.partner_status not in (ST_WORK, ST_AGREE, ST_CLIENT):
            raise PartnerError(f'Работа уже: {STATUS_TITLES.get(task.partner_status, "")}')
        task.partner_status = ST_WAIT
        task.done_by = by
        self._touch(task)
        return task

    def pay(self, tasks, method, note=None, employee_id=None):
        """
        Оплатили партнёру. Наличные — РКО, безнал — расходный ордер по
        безналу, другое — только пометка. Несколько работ одного партнёра —
        один ордер на сумму, в пометке — какие работы.
        """
        from services.cash_service import CashService
        from models.cash import KIND_OUT, METHOD_CASH, METHOD_NONCASH

        tasks = list(tasks)
        if not tasks:
            raise PartnerError('Отметьте, что оплачиваем')
        if method not in PAY_TITLES:
            raise PartnerError('Выберите, чем платим')
        for task in tasks:
            if task.partner_status == ST_PAID:
                raise PartnerError(f'{number_of(task)} уже оплачена')
            if task.partner_status == ST_REFUSED:
                raise PartnerError(f'{number_of(task)} — отказ, платить нечего')
            if task.partner_price is None:
                raise PartnerError(f'У {number_of(task)} не указана цена партнёра')
        orders_made = []
        if method in (PAY_CASH, PAY_NONCASH):
            cash = CashService(self.db)
            groups = {}
            for task in tasks:
                groups.setdefault(task.counterparty_uid, []).append(task)
            for party_uid, group in groups.items():
                party = self.db.query(Counterparty).filter(Counterparty.uid == party_uid).first()
                total = round(sum(t.partner_price for t in group), 2)
                text = (f'{party.name if party else "Партнёр"}: '
                        + ', '.join(f'{number_of(t)} {t.title}' for t in group))
                if note:
                    text += f' · {note}'
                row = cash.create(KIND_OUT, CASH_CATEGORY, total,
                                  METHOD_CASH if method == PAY_CASH else METHOD_NONCASH,
                                  note=text[:300], employee_id=employee_id,
                                  check_category=False, commit=False)
                orders_made.append(row)
        moment = get_moscow_time()
        for task in tasks:
            task.partner_status = ST_PAID
            task.pay_method = method
            task.pay_note = (note or '')[:300] or None
            task.paid_at = moment
            task.done_at = task.done_at or moment
            self._touch(task)
        self.db.commit()
        return orders_made

    # ------------------------------------------------------------------
    # Зарплата
    # ------------------------------------------------------------------

    def accrual(self, task, line_total):
        """
        Кому сколько с работы: [(employee_id, сумма, разбор)]. Маржа без
        цены партнёра не считается — досчитается, когда её впишут.
        """
        to = task.salary_to or SAL_NONE
        if to == SAL_NONE or not task.salary_mode:
            return []
        people = [task.creator_id] if to == SAL_CREATOR else _ids(task.salary_people)
        people = [p for p in people if p]
        if not people:
            return []
        margin = None if task.partner_price is None else max(0.0, line_total - task.partner_price)
        mode, value = task.salary_mode, float(task.salary_value or 0)
        if mode == MODE_MARGIN_ALL:
            total = margin
        elif mode == MODE_PRICE_PCT:
            total = line_total * value / 100
        elif mode == MODE_MARGIN_PCT:
            total = None if margin is None else margin * value / 100
        else:
            total = value
        if total is None:
            return [(p, 0.0, {'pending': True}) for p in people]
        share = total / len(people)
        return [(p, share, {'mode': mode, 'value': value, 'margin': margin}) for p in people]

    def settle_late(self, task):
        """
        Цену партнёра вписали после оплаты наряда — досчитать зарплату от
        маржи: начисляем разницу к уже начисленному по этой работе.
        """
        import json
        from services.order_service import OrderService
        from services.salary_service import read_detail

        order = self.order_of(task)
        line = self.line_of(task)
        if order is None or order.status != 'paid' or line is None:
            return []
        expected = {}
        for employee_id, amount, _info in self.accrual(task, OrderService.item_total(line)):
            expected[employee_id] = expected.get(employee_id, 0.0) + amount
        got = {}
        for row in self.db.query(SalaryTransaction).filter(
                SalaryTransaction.work_order_id == order.id).all():
            for part in (read_detail(row) or {}).get('lines') or []:
                if part.get('partner_uid') == task.uid:
                    got[row.employee_id] = got.get(row.employee_id, 0.0) + (part.get('amount') or 0)
        made = []
        for employee_id in set(expected) | set(got):
            delta = round(expected.get(employee_id, 0.0) - got.get(employee_id, 0.0), 2)
            if not delta:
                continue
            detail = {'lines': [{'name': f'Партнёр: {task.title} (досчитано)', 'amount': delta,
                                 'partner_uid': task.uid, 'direction': line.direction or 'tire',
                                 'base': round(OrderService.item_total(line), 2), 'shared': 1}],
                      'skipped': []}
            row = SalaryTransaction(employee_id=employee_id, work_order_id=order.id, amount=delta,
                                    detail=json.dumps(detail, ensure_ascii=False))
            self.db.add(row)
            made.append(row)
        self.db.commit()
        return made
