"""
Цифры дашборда: выручка, услуги, мастера, наряды, смены.

Считается по тем же правилам, что и отчёты в программе цеха. Это не
пожелание, а условие: если дашборд покажет выручку иначе, чем вкладка
«Отчёты», им перестанут пользоваться оба.

Правила, которые легко нарушить и трудно заметить:

  · удалённые наряды не считаются нигде — ни в выручке, ни в зарплате;
  · возврат вычитается из того дня, когда вернули, а не когда работали:
    иначе вчерашняя выручка меняется задним числом, и сходить с кассой
    она перестанет;
  · гарантийные наряды прибавляют машину, но не деньги;
  · зарплата не пересчитывается — берётся начисленная в цеху.
"""
from datetime import datetime, time, timedelta

from sqlalchemy import func

from app.models import (Visit, VisitItem, SalaryAccrual, ShopEmployee,
                        ShopShift)


def day_bounds(day_from, day_to):
    """Границы периода: с начала первого дня до конца последнего."""
    start = datetime.combine(day_from, time.min)
    end = datetime.combine(day_to, time.max)
    return start, end


class DashboardService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Общее
    # ------------------------------------------------------------------

    def _orders_query(self, start, end):
        """Наряды периода: оплаченные, не удалённые."""
        return self.db.query(Visit).filter(
            Visit.is_deleted.is_(False),
            Visit.visited_at >= start,
            Visit.visited_at <= end)

    def _refunds_in(self, start, end):
        """
        Возвраты, оформленные в этом периоде.

        Отдельным запросом: сам наряд мог быть месяц назад, а деньги
        вернули сегодня — и вычесть их надо из сегодняшнего дня.
        """
        return self.db.query(Visit).filter(
            Visit.is_deleted.is_(False),
            Visit.refunded_amount > 0,
            Visit.refunded_at.isnot(None),
            Visit.refunded_at >= start,
            Visit.refunded_at <= end)

    # ------------------------------------------------------------------
    # Сводка
    # ------------------------------------------------------------------

    def summary(self, day_from, day_to):
        start, end = day_bounds(day_from, day_to)
        orders = self._orders_query(start, end).all()

        revenue = sum(order.total_amount or 0.0 for order in orders)
        refunded = sum(order.refunded_amount or 0.0
                       for order in self._refunds_in(start, end).all())

        cash = sum(order.total_amount or 0.0 for order in orders
                   if order.payment_method == 'cash')
        card = sum(order.total_amount or 0.0 for order in orders
                   if order.payment_method == 'card')

        consumables = sum(order.consumables_amount or 0.0 for order in orders)
        warranty = [order for order in orders if order.is_warranty]

        salary = self.db.query(func.sum(SalaryAccrual.amount)).join(
            Visit, SalaryAccrual.visit_id == Visit.id).filter(
            Visit.is_deleted.is_(False),
            Visit.visited_at >= start,
            Visit.visited_at <= end).scalar() or 0.0

        paid_orders = [order for order in orders if (order.total_amount or 0) > 0]
        average = round(revenue / len(paid_orders), 2) if paid_orders else 0.0

        return {
            'from': day_from,
            'to': day_to,
            'revenue': round(revenue, 2),
            'refunded': round(refunded, 2),
            # Чистая выручка: за вычетом возвратов этого периода
            'net_revenue': round(revenue - refunded, 2),
            'cars': len(orders),
            'warranty_cars': len(warranty),
            'average_check': average,
            'cash': round(cash, 2),
            'card': round(card, 2),
            'consumables': round(consumables, 2),
            'salary': round(float(salary), 2),
            # Что осталось цеху после зарплаты и материалов. Не прибыль:
            # аренду, налоги и прочее программа не знает и знать не должна
            'left': round(revenue - refunded - float(salary) - consumables, 2),
            'by_day': self.by_day(day_from, day_to),
        }

    def by_day(self, day_from, day_to):
        """Выручка и машины по дням — для графика."""
        start, end = day_bounds(day_from, day_to)

        buckets = {}
        day = day_from
        while day <= day_to:
            buckets[day.isoformat()] = {'day': day.isoformat(),
                                        'revenue': 0.0, 'cars': 0}
            day += timedelta(days=1)

        for order in self._orders_query(start, end).all():
            key = order.visited_at.date().isoformat()
            if key not in buckets:
                continue
            buckets[key]['revenue'] += order.total_amount or 0.0
            buckets[key]['cars'] += 1

        for order in self._refunds_in(start, end).all():
            key = order.refunded_at.date().isoformat()
            if key in buckets:
                buckets[key]['revenue'] -= order.refunded_amount or 0.0

        rows = list(buckets.values())
        for row in rows:
            row['revenue'] = round(row['revenue'], 2)
        return rows

    # ------------------------------------------------------------------
    # Услуги
    # ------------------------------------------------------------------

    def services(self, day_from, day_to):
        """
        Что продавалось: услуга, сколько раз, на какую сумму.

        Суммы позиций берём как есть: все скидки — общая, автоматическая,
        на диски — уже сидят в цене позиции, и вычитать их второй раз
        значило бы занизить выручку.
        """
        start, end = day_bounds(day_from, day_to)

        rows = self.db.query(
            VisitItem.service_name,
            func.sum(VisitItem.quantity),
            func.sum(VisitItem.total),
            func.sum(VisitItem.consumable_cost * VisitItem.quantity),
        ).join(Visit, VisitItem.visit_id == Visit.id).filter(
            Visit.is_deleted.is_(False),
            Visit.visited_at >= start,
            Visit.visited_at <= end,
        ).group_by(VisitItem.service_name).all()

        total = sum(float(row[2] or 0) for row in rows) or 1.0

        result = [{
            'service_name': row[0],
            'quantity': int(row[1] or 0),
            'amount': round(float(row[2] or 0), 2),
            'consumables': round(float(row[3] or 0), 2),
            'share': round(float(row[2] or 0) / total * 100, 1),
        } for row in rows]

        result.sort(key=lambda item: item['amount'], reverse=True)
        return result

    # ------------------------------------------------------------------
    # Мастера
    # ------------------------------------------------------------------

    def masters(self, day_from, day_to):
        """Выработка и начисления по мастерам за период."""
        start, end = day_bounds(day_from, day_to)

        rows = self.db.query(
            SalaryAccrual.employee_shop_id,
            func.count(SalaryAccrual.id),
            func.sum(SalaryAccrual.amount),
            func.sum(Visit.salary_base),
            func.sum(Visit.total_amount),
        ).join(Visit, SalaryAccrual.visit_id == Visit.id).filter(
            Visit.is_deleted.is_(False),
            Visit.visited_at >= start,
            Visit.visited_at <= end,
        ).group_by(SalaryAccrual.employee_shop_id).all()

        people = {row.shop_id: row
                  for row in self.db.query(ShopEmployee).all()}

        result = []
        for shop_id, orders, salary, base, revenue in rows:
            person = people.get(shop_id)
            result.append({
                'employee_shop_id': shop_id,
                'title': person.title if person else f'№{shop_id}',
                'name': person.name if person else None,
                'salary_percent': person.salary_percent if person else None,
                'orders': int(orders or 0),
                'salary': round(float(salary or 0), 2),
                # База — сумма по нарядам, где мастер участвовал. Если
                # работали вдвоём, она у обоих одна и та же: это объём
                # работы, а не его доля в деньгах
                'salary_base': round(float(base or 0), 2),
                'revenue': round(float(revenue or 0), 2),
            })

        result.sort(key=lambda item: item['salary'], reverse=True)
        return result

    # ------------------------------------------------------------------
    # Наряды
    # ------------------------------------------------------------------

    def orders(self, day_from, day_to, employee_shop_id=None,
               payment_method=None, limit=500):
        start, end = day_bounds(day_from, day_to)
        query = self._orders_query(start, end)

        if payment_method:
            query = query.filter(Visit.payment_method == payment_method)

        if employee_shop_id is not None:
            query = query.join(
                SalaryAccrual, SalaryAccrual.visit_id == Visit.id).filter(
                SalaryAccrual.employee_shop_id == employee_shop_id)

        rows = query.order_by(Visit.visited_at.desc()).limit(limit).all()
        return [self._order_row(order) for order in rows]

    def _order_row(self, order):
        return {
            'shop_id': order.shop_id,
            'visited_at': order.visited_at,
            'license_plate': order.license_plate,
            'total_amount': round(order.total_amount or 0.0, 2),
            'payment_method': order.payment_method,
            'is_warranty': order.is_warranty,
            'refunded_amount': round(order.refunded_amount or 0.0, 2),
            # В отчёты удалённый наряд не идёт, но открыть его карточку
            # можно: «почему выручка меньше, чем я помню» разбирается
            # именно по таким
            'is_deleted': order.is_deleted,
            'masters': [self._master_title(row.employee_shop_id)
                        for row in order.accruals],
            'services': order.services,
        }

    def _master_title(self, shop_id):
        person = self.db.query(ShopEmployee).filter(
            ShopEmployee.shop_id == shop_id).first()
        return person.title if person else f'№{shop_id}'

    def order_card(self, shop_id, employee_shop_id=None):
        """
        Наряд целиком: позиции, расходники, время, начисления.

        employee_shop_id — если смотрит мастер. Тогда отдаём только его
        наряд и только его начисление: чужие деньги он видеть не должен.
        """
        order = self.db.query(Visit).filter(Visit.shop_id == shop_id).first()
        if order is None:
            return None

        accruals = list(order.accruals)
        if employee_shop_id is not None:
            if not any(row.employee_shop_id == employee_shop_id
                       for row in accruals):
                return None
            accruals = [row for row in accruals
                        if row.employee_shop_id == employee_shop_id]

        minutes = None
        if order.started_at and order.finished_at:
            minutes = int((order.finished_at - order.started_at).total_seconds() // 60)

        card = self._order_row(order)
        card.update({
            'vehicle_type': order.vehicle_type,
            'wheel_diameter': order.wheel_diameter,
            'consumables_amount': round(order.consumables_amount or 0.0, 2),
            'salary_base': round(order.salary_base or 0.0, 2),
            'general_discount': order.general_discount,
            'rim_discount': order.rim_discount,
            'auto_discount': order.auto_discount,
            'refund_type': order.refund_type,
            'refund_reason': order.refund_reason,
            'recommendations': order.recommendations,
            'planned_minutes': order.planned_minutes,
            'actual_minutes': minutes,
            'shift_shop_id': order.shift_shop_id,
            'items': [{
                'service_name': item.service_name,
                'quantity': item.quantity,
                'unit_price': round(item.unit_price or 0.0, 2),
                'discount_percent': item.discount_percent,
                'total': round(item.total or 0.0, 2),
                'consumable_cost': round(item.consumable_cost or 0.0, 2),
                'comment': item.comment,
            } for item in order.items],
            'accruals': [{
                'employee_shop_id': row.employee_shop_id,
                'title': self._master_title(row.employee_shop_id),
                'amount': round(row.amount or 0.0, 2),
            } for row in accruals],
        })
        return card

    # ------------------------------------------------------------------
    # Смены
    # ------------------------------------------------------------------

    def shifts(self, day_from, day_to):
        start, end = day_bounds(day_from, day_to)
        rows = self.db.query(ShopShift).filter(
            ShopShift.started_at >= start,
            ShopShift.started_at <= end,
        ).order_by(ShopShift.started_at.desc()).all()

        return [{
            'shop_id': row.shop_id,
            'started_at': row.started_at,
            'ended_at': row.ended_at,
            'status': row.status,
            'open_posts': row.open_posts,
            'total_salary': round(row.total_salary or 0.0, 2),
        } for row in rows]

    def shift_salary(self, shift_shop_id, employee_shop_id=None):
        """
        Начисления за смену — то, что открывается кнопкой.

        По каждому сотруднику: итог и строки нарядов. В строке только
        номер наряда, машина и сумма: этого хватает, чтобы мастер узнал
        свою работу, а разбираться в составе наряда надо не здесь.
        """
        shift = self.db.query(ShopShift).filter(
            ShopShift.shop_id == shift_shop_id).first()

        rows = self.db.query(SalaryAccrual, Visit).join(
            Visit, SalaryAccrual.visit_id == Visit.id).filter(
            Visit.shift_shop_id == shift_shop_id,
            Visit.is_deleted.is_(False),
        ).order_by(Visit.shop_id).all()

        if employee_shop_id is not None:
            rows = [pair for pair in rows
                    if pair[0].employee_shop_id == employee_shop_id]

        people = {}
        for accrual, order in rows:
            emp_id = accrual.employee_shop_id
            if emp_id not in people:
                people[emp_id] = {
                    'employee_shop_id': emp_id,
                    'title': self._master_title(emp_id),
                    'salary': 0.0,
                    'orders': [],
                }
            people[emp_id]['salary'] += accrual.amount or 0.0
            people[emp_id]['orders'].append({
                'order_id': order.shop_id,
                'license_plate': order.license_plate,
                'amount': round(accrual.amount or 0.0, 2),
            })

        for person in people.values():
            person['salary'] = round(person['salary'], 2)

        return {
            'shift': {
                'shop_id': shift_shop_id,
                'started_at': shift.started_at if shift else None,
                'ended_at': shift.ended_at if shift else None,
                'status': shift.status if shift else None,
                'open_posts': shift.open_posts if shift else None,
            },
            # Пока смена открыта, сумма растёт с каждой оплатой. Говорим
            # об этом прямо: иначе мастер запомнит промежуточную цифру
            'is_final': bool(shift and shift.status == 'closed'),
            'employees': sorted(people.values(),
                                key=lambda item: item['salary'], reverse=True),
            'total': round(sum(item['salary'] for item in people.values()), 2),
        }

    def current_shift(self):
        return self.db.query(ShopShift).filter(
            ShopShift.status == 'open').order_by(
            ShopShift.started_at.desc()).first()
