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
            base = max(0.0, OrderService.item_total(item)
                       - OrderService.item_consumables(item))
            name = item.service.name if item.service else f'Позиция №{item.id}'
            work.append((name, base))
        return work

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
        if not order or not order.employee_ids:
            return {}, []
        employee_ids = [int(i.strip()) for i in order.employee_ids.split(',')
                        if i.strip()]
        return split(self._work_of(order_id), self._people_of(employee_ids))

    def process_payment(self, order_id: int, payment_method: str, total_amount: float):
        """
        Провести оплату и начислить зарплату.

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

        # Используем сохранённых сотрудников из наряда
        if not order.employee_ids:
            raise ValueError("Нет сотрудников в наряде")

        employee_ids = [int(id.strip()) for id in order.employee_ids.split(',')
                        if id.strip()]

        # Зарплата считается по каждой услуге отдельно, от её стоимости
        # минус расходники. Раньше база была одна на весь наряд — «итог
        # минус себестоимость», и у товара себестоимостью шла закупка:
        # наценка с вентиля попадала мастеру в процент, хотя с товаров
        # решили не начислять
        people, nobody = split(self._work_of(order_id),
                               self._people_of(employee_ids))

        for employee_id in employee_ids:
            share = people[employee_id]
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

        order.paid_at = get_moscow_time()
        order.payment_method = payment_method
        order.total_amount = total_amount
        order.consumables_amount = order_service.calculate_consumables(order_id)
        order.salary_base = order_service.calculate_salary_base(order_id)
        order.status = 'paid'

        self.db.commit()

        # Оплачен — машина ушла с поста: место в живой очереди закрыто,
        # пост свободен для следующего
        from services.live_queue_service import LiveQueueService
        LiveQueueService(self.db).order_closed(order_id)

        # Владелец смотрит в дашборд сразу после оплаты, и ждать
        # десять минут ему незачем
        from services import sync_nudge

        sync_nudge.request('наряд оплачен')

        return nobody


def read_detail(transaction):
    """Разбор начисления: {'lines': [...], 'skipped': [...]} или None."""
    raw = getattr(transaction, 'detail', None)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None
