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

from app.models import (Visit, VisitItem, SalaryAccrual, SalaryPayout,
                        ShopEmployee, ShopShift, PENDING)
from app.utils import now as shop_now


def day_bounds(day_from, day_to):
    """Границы периода: с начала первого дня до конца последнего."""
    start = datetime.combine(day_from, time.min)
    end = datetime.combine(day_to, time.max)
    return start, end


class DashboardService:
    def __init__(self, db, account_id=None, shop_ids=None):
        """
        account_id — чей дашборд. shop_ids — какие точки показывать.

        Пусто и то и другое — считаем по всему, что есть: так работает
        сервер с единственным шиномонтажом, где выбирать не из чего.
        """
        self.db = db
        self.account_id = account_id
        self.shop_ids = list(shop_ids) if shop_ids else None

    def _only_mine(self, query, model=None):
        """Сузить выборку до выбранных точек."""
        model = model or Visit
        if self.shop_ids:
            return query.filter(model.shop_id.in_(self.shop_ids))
        return query

    def _shop_titles(self):
        """Названия точек — чтобы к сотруднику приписать, где он работает."""
        rows = self.db.query(ShopEmployee.shop_id).distinct().all()
        del rows

        from app.models import Shop

        query = self.db.query(Shop)
        if self.account_id is not None:
            query = query.filter(Shop.account_id == self.account_id)

        return {shop.id: shop.name for shop in query.all()}

    # ------------------------------------------------------------------
    # Общее
    # ------------------------------------------------------------------

    def _orders_query(self, start, end):
        """Наряды периода: оплаченные, не удалённые, из выбранных точек."""
        return self._only_mine(self.db.query(Visit).filter(
            Visit.is_deleted.is_(False),
            Visit.visited_at >= start,
            Visit.visited_at <= end))

    def _refunds_in(self, start, end):
        """
        Возвраты, оформленные в этом периоде.

        Отдельным запросом: сам наряд мог быть месяц назад, а деньги
        вернули сегодня — и вычесть их надо из сегодняшнего дня.
        """
        return self._only_mine(self.db.query(Visit).filter(
            Visit.is_deleted.is_(False),
            Visit.refunded_amount > 0,
            Visit.refunded_at.isnot(None),
            Visit.refunded_at >= start,
            Visit.refunded_at <= end))

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

        salary = self._only_mine(
            self.db.query(func.sum(SalaryAccrual.amount)).join(
                Visit, SalaryAccrual.visit_id == Visit.id).filter(
                Visit.is_deleted.is_(False),
                Visit.visited_at >= start,
                Visit.visited_at <= end)).scalar() or 0.0

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
            VisitItem.is_extra,
        ).join(Visit, VisitItem.visit_id == Visit.id).filter(
            Visit.is_deleted.is_(False),
            Visit.visited_at >= start,
            Visit.visited_at <= end,
        )
        rows = self._only_mine(rows).group_by(
            VisitItem.service_name, VisitItem.is_extra).all()

        total = sum(float(row[2] or 0) for row in rows) or 1.0

        result = [{
            'service_name': row[0],
            'quantity': int(row[1] or 0),
            'amount': round(float(row[2] or 0), 2),
            'consumables': round(float(row[3] or 0), 2),
            'share': round(float(row[2] or 0) / total * 100, 1),
            'is_extra': bool(row[4]),
        } for row in rows]

        result.sort(key=lambda item: item['amount'], reverse=True)
        return result

    def sales(self, day_from, day_to):
        """
        Сводка по продажам: основное отдельно, допродажи отдельно.

        Доля допов — показатель работы приёмки, а не бухгалтерии. Машин
        за день приезжает примерно одинаково; разница в выручке между
        хорошим месяцем и плохим обычно сидит именно в том, предложили
        человеку что-то сверх или просто перекинули колёса.
        """
        rows = self.services(day_from, day_to)

        main = [row for row in rows if not row['is_extra']]
        extra = [row for row in rows if row['is_extra']]

        main_sum = round(sum(row['amount'] for row in main), 2)
        extra_sum = round(sum(row['amount'] for row in extra), 2)
        total = main_sum + extra_sum

        return {
            'main': main,
            'extra': extra,
            'main_amount': main_sum,
            'extra_amount': extra_sum,
            'total_amount': round(total, 2),

            # Сколько рублей из ста принесли допродажи
            'extra_share': round(extra_sum / total * 100, 1) if total else 0.0,

            # Пока прайс не размечен, допов нет вовсе — и показывать
            # «доля допродаж: 0%» значит врать: их не ноль, их просто
            # не отличили
            'marked': bool(extra),
        }

    # ------------------------------------------------------------------
    # Мастера
    # ------------------------------------------------------------------

    def masters(self, day_from, day_to):
        """Выработка и начисления по мастерам за период."""
        start, end = day_bounds(day_from, day_to)

        rows = self._only_mine(self.db.query(
            Visit.shop_id,
            SalaryAccrual.employee_local_id,
            func.count(SalaryAccrual.id),
            func.sum(SalaryAccrual.amount),
            func.sum(Visit.salary_base),
            func.sum(Visit.total_amount),
        ).join(Visit, SalaryAccrual.visit_id == Visit.id).filter(
            Visit.is_deleted.is_(False),
            Visit.visited_at >= start,
            Visit.visited_at <= end,
        )).group_by(Visit.shop_id, SalaryAccrual.employee_local_id).all()

        people = self._people()
        titles = self._shop_titles()

        result = []
        for shop_id, local_id, orders, salary, base, revenue in rows:
            person = people.get((shop_id, local_id))
            result.append({
                'shop_id': shop_id,
                'shop_name': titles.get(shop_id),
                'employee_local_id': local_id,
                'title': person.title if person else f'№{local_id}',
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

    def _people(self):
        """
        Сотрудники по паре «точка и номер».

        Именно паре: номер сотрудника уникален в своём цеху, и мастер
        №1 из соседней точки — другой человек.
        """
        query = self.db.query(ShopEmployee)
        if self.shop_ids:
            query = query.filter(ShopEmployee.shop_id.in_(self.shop_ids))

        return {(row.shop_id, row.local_id): row for row in query.all()}

    # ------------------------------------------------------------------
    # Зарплата: сколько начислено, сколько выдано, сколько осталось
    # ------------------------------------------------------------------

    def salary_balances(self):
        """
        Остатки по всем сотрудникам за всё время.

        Считается от начала работы, а не за период: невыданный хвост
        прошлого месяца — такой же долг, как и сегодняшний.

        Выплаты, отмеченные владельцем и ещё не забранные цехом, в
        остаток уже входят — иначе владелец, отметив перевод, увидит
        прежний долг и переведёт второй раз.
        """
        accrued = dict(((shop_id, local_id), total) for shop_id, local_id, total
                       in self._only_mine(self.db.query(
                           Visit.shop_id,
                           SalaryAccrual.employee_local_id,
                           func.sum(SalaryAccrual.amount),
                       ).join(Visit, SalaryAccrual.visit_id == Visit.id).filter(
                           Visit.is_deleted.is_(False),
                       )).group_by(Visit.shop_id,
                                   SalaryAccrual.employee_local_id).all())

        paid = dict(((shop_id, local_id), total) for shop_id, local_id, total
                    in self._only_mine(self.db.query(
                        SalaryPayout.shop_id,
                        SalaryPayout.employee_local_id,
                        func.sum(SalaryPayout.amount),
                    ), SalaryPayout).group_by(
                        SalaryPayout.shop_id,
                        SalaryPayout.employee_local_id).all())

        waiting = dict(((shop_id, local_id), total) for shop_id, local_id, total
                       in self._only_mine(self.db.query(
                           SalaryPayout.shop_id,
                           SalaryPayout.employee_local_id,
                           func.sum(SalaryPayout.amount),
                       ).filter(SalaryPayout.sync_state == PENDING),
                           SalaryPayout).group_by(
                           SalaryPayout.shop_id,
                           SalaryPayout.employee_local_id).all())

        titles = self._shop_titles()

        query = self.db.query(ShopEmployee).filter(
            ShopEmployee.is_active.is_(True))
        if self.shop_ids:
            query = query.filter(ShopEmployee.shop_id.in_(self.shop_ids))

        rows = []
        for person in query.order_by(ShopEmployee.shop_id,
                                     ShopEmployee.local_id).all():
            key = (person.shop_id, person.local_id)
            earned = round(float(accrued.get(key, 0) or 0), 2)
            given = round(float(paid.get(key, 0) or 0), 2)

            rows.append({
                'shop_id': person.shop_id,
                'shop_name': titles.get(person.shop_id),
                'employee_local_id': person.local_id,
                'title': person.title,
                'accrued': earned,
                'paid': given,
                'balance': round(earned - given, 2),
                # Отмечено владельцем, но цех ещё не забрал
                'waiting': round(float(waiting.get(key, 0) or 0), 2),
            })

        return rows

    def payout_history(self, limit=100):
        rows = self._only_mine(
            self.db.query(SalaryPayout), SalaryPayout).order_by(
            SalaryPayout.paid_at.desc().nullslast(),
            SalaryPayout.id.desc()).limit(limit).all()

        people = self._people()
        titles = self._shop_titles()

        return [{
            'shop_id': row.shop_id,
            'shop_name': titles.get(row.shop_id),
            'employee_local_id': row.employee_local_id,
            'title': (people[(row.shop_id, row.employee_local_id)].title
                      if (row.shop_id, row.employee_local_id) in people
                      else f'№{row.employee_local_id}'),
            'amount': round(row.amount or 0.0, 2),
            'method': row.method,
            'paid_at': row.paid_at,
            'comment': row.comment,
            'is_advance': row.is_advance,
            'source': row.source,
            # Выплата из дашборда живёт с отметкой, пока цех её не забрал
            'waiting': row.sync_state == PENDING,
        } for row in rows]

    def pay_to_card(self, employee_local_id, amount, comment=None,
                    author_id=None, shop_id=None):
        """
        Отметить перевод зарплаты на карту.

        Запись рождается здесь и ждёт цеха: до обмена остаток в базе
        шиномонтажа ещё прежний. Показываем это честно, отметкой «ждёт
        цеха», а не делаем вид, что деньги уже учтены везде.
        """
        query = self.db.query(ShopEmployee).filter(
            ShopEmployee.local_id == employee_local_id)

        if shop_id is not None:
            query = query.filter(ShopEmployee.shop_id == shop_id)
        elif self.shop_ids:
            query = query.filter(ShopEmployee.shop_id.in_(self.shop_ids))

        people = query.all()
        if not people:
            raise ValueError('Такого сотрудника нет')
        if len(people) > 1:
            # Номер сотрудника уникален только внутри своей точки:
            # выдать деньги «мастеру №1» вообще — значит выдать наугад
            raise ValueError('Укажите точку: сотрудник с таким номером '
                             'есть не в одной')

        person = people[0]

        try:
            amount = round(float(amount), 2)
        except (TypeError, ValueError):
            raise ValueError('Сумма должна быть числом')

        if amount <= 0:
            raise ValueError('Сумма должна быть больше нуля')

        payout = SalaryPayout(
            shop_id=person.shop_id,
            employee_local_id=employee_local_id,
            amount=amount,
            method='card',
            paid_at=shop_now(),
            comment=(comment or '').strip() or None,
            source='dashboard',
            sync_state=PENDING,
            created_by_id=author_id)

        self.db.add(payout)
        self.db.commit()
        self.db.refresh(payout)
        return payout

    # ------------------------------------------------------------------
    # Наряды
    # ------------------------------------------------------------------

    def orders(self, day_from, day_to, employee_local_id=None,
               payment_method=None, limit=500):
        start, end = day_bounds(day_from, day_to)
        query = self._orders_query(start, end)

        if payment_method:
            query = query.filter(Visit.payment_method == payment_method)

        if employee_local_id is not None:
            query = query.join(
                SalaryAccrual, SalaryAccrual.visit_id == Visit.id).filter(
                SalaryAccrual.employee_local_id == employee_local_id)

        rows = query.order_by(Visit.visited_at.desc()).limit(limit).all()
        return [self._order_row(order) for order in rows]

    def _order_row(self, order):
        return {
            'local_id': order.local_id,
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
            'masters': [self._master_title(row.employee_local_id, order.shop_id)
                        for row in order.accruals],
            'services': order.services,
        }

    def _master_title(self, local_id, shop_id=None):
        query = self.db.query(ShopEmployee).filter(
            ShopEmployee.local_id == local_id)
        if shop_id is not None:
            query = query.filter(ShopEmployee.shop_id == shop_id)
        elif self.shop_ids:
            query = query.filter(ShopEmployee.shop_id.in_(self.shop_ids))

        person = query.first()
        return person.title if person else f'№{local_id}'

    def order_card(self, local_id):
        """Наряд целиком: позиции, расходники, время, начисления."""
        order = self._only_mine(self.db.query(Visit).filter(
            Visit.local_id == local_id)).first()
        if order is None:
            return None

        accruals = list(order.accruals)

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
            'shift_local_id': order.shift_local_id,
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
                'employee_local_id': row.employee_local_id,
                'title': self._master_title(row.employee_local_id,
                                            order.shop_id),
                'amount': round(row.amount or 0.0, 2),
            } for row in accruals],
        })
        return card

    # ------------------------------------------------------------------
    # Смены
    # ------------------------------------------------------------------

    def shifts(self, day_from, day_to):
        start, end = day_bounds(day_from, day_to)
        rows = self._only_mine(self.db.query(ShopShift).filter(
            ShopShift.started_at >= start,
            ShopShift.started_at <= end,
        ), ShopShift).order_by(ShopShift.started_at.desc()).all()

        titles = self._shop_titles()

        return [{
            'local_id': row.local_id,
            'shop_id': row.shop_id,
            'shop_name': titles.get(row.shop_id),
            'started_at': row.started_at,
            'ended_at': row.ended_at,
            'status': row.status,
            'open_posts': row.open_posts,
            'total_salary': round(row.total_salary or 0.0, 2),
        } for row in rows]

    def shift_salary(self, shift_local_id, shop_id=None):
        """
        Начисления за смену — то, что открывается кнопкой.

        По каждому сотруднику: итог и строки нарядов. В строке только
        номер наряда, машина и сумма: этого хватает, чтобы мастер узнал
        свою работу, а разбираться в составе наряда надо не здесь.
        """
        query = self.db.query(ShopShift).filter(
            ShopShift.local_id == shift_local_id)
        if shop_id is not None:
            query = query.filter(ShopShift.shop_id == shop_id)
        else:
            query = self._only_mine(query, ShopShift)
        shift = query.first()

        # Номер смены тоже свой у каждой точки: без сужения сюда попадут
        # чужие наряды с тем же номером смены
        orders = self.db.query(SalaryAccrual, Visit).join(
            Visit, SalaryAccrual.visit_id == Visit.id).filter(
            Visit.shift_local_id == shift_local_id,
            Visit.is_deleted.is_(False),
        )
        if shift is not None:
            orders = orders.filter(Visit.shop_id == shift.shop_id)
        else:
            orders = self._only_mine(orders)

        rows = orders.order_by(Visit.local_id).all()

        people = {}
        for accrual, order in rows:
            emp_id = accrual.employee_local_id
            if emp_id not in people:
                people[emp_id] = {
                    'employee_local_id': emp_id,
                    'title': self._master_title(emp_id, order.shop_id),
                    'salary': 0.0,
                    'orders': [],
                }
            people[emp_id]['salary'] += accrual.amount or 0.0
            people[emp_id]['orders'].append({
                'order_id': order.local_id,
                'license_plate': order.license_plate,
                'amount': round(accrual.amount or 0.0, 2),
            })

        for person in people.values():
            person['salary'] = round(person['salary'], 2)

        return {
            'shift': {
                'local_id': shift_local_id,
                'shop_id': shift.shop_id if shift else None,
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
        return self._only_mine(self.db.query(ShopShift).filter(
            ShopShift.status == 'open'), ShopShift).order_by(
            ShopShift.started_at.desc()).first()
