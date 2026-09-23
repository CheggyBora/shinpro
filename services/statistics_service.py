"""
Сервис для расчёта статистики продаж
"""
from datetime import datetime
from models import WorkOrder, WorkOrderItem, SalaryTransaction
from sqlalchemy import func
from sqlalchemy.orm import joinedload

class StatisticsService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Отчёт по нарядам
    # ------------------------------------------------------------------

    def _salary_by_order(self, order_ids):
        """
        Начисленная зарплата по каждому наряду в разрезе мастеров.

        Суммируем транзакции: у удалённых нарядов есть обратные записи
        с отрицательной суммой, поэтому итог получается чистый.
        """
        if not order_ids:
            return {}

        rows = self.db.query(
            SalaryTransaction.work_order_id,
            SalaryTransaction.employee_id,
            func.sum(SalaryTransaction.amount)
        ).filter(
            SalaryTransaction.work_order_id.in_(order_ids)
        ).group_by(
            SalaryTransaction.work_order_id, SalaryTransaction.employee_id
        ).all()

        result = {}
        for order_id, employee_id, amount in rows:
            result.setdefault(order_id, []).append({
                'employee_id': employee_id,
                'amount': round(float(amount or 0), 2),
            })
        return result

    def get_orders_report(self, date_from: datetime, date_to: datetime):
        """
        Данные по каждому наряду за период.

        По каждому наряду видно, из чего сложился результат: сумма без
        скидки, скидка, расходники, зарплата мастеров и что осталось
        шиномонтажу.
        """
        from services.order_service import OrderService

        orders = self.db.query(WorkOrder).filter(
            WorkOrder.paid_at >= date_from,
            WorkOrder.paid_at <= date_to,
            WorkOrder.status == 'paid',
            WorkOrder.is_deleted == False
        ).order_by(WorkOrder.paid_at.desc()).all()

        salaries = self._salary_by_order([o.id for o in orders])

        report = []
        for order in orders:
            items = self.db.query(WorkOrderItem).options(
                joinedload(WorkOrderItem.service)
            ).filter_by(work_order_id=order.id).all()

            full_price = sum(OrderService.item_total_without_discount(i) for i in items)
            total = float(order.total_amount or 0)
            consumables = float(order.consumables_amount or 0)

            order_salaries = salaries.get(order.id, [])
            salary_total = round(sum(s['amount'] for s in order_salaries), 2)

            refunded = float(order.refunded_amount or 0)
            # В выручку попадает то, что осталось после возврата
            net = round(total - refunded, 2)

            report.append({
                'order': order,
                'id': order.id,
                'paid_at': order.paid_at,
                'license_plate': order.car.license_plate if order.car else '—',
                'client_name': order.client.name if order.client else None,
                'client_phone': order.client.phone if order.client else None,
                'items': items,
                'services_count': sum(i.quantity for i in items),
                'full_price': round(full_price, 2),
                'discount': round(full_price - total, 2),
                'total': round(total, 2),
                'consumables': round(consumables, 2),
                'salaries': order_salaries,
                'salary_total': salary_total,
                'refunded': round(refunded, 2),
                'net': net,
                'is_warranty': bool(order.is_warranty),
                'refund_type': order.refund_type,
                'refund_reason': order.refund_reason,
                # Что осталось шиномонтажу после возврата, материалов и зарплаты
                'margin': round(net - consumables - salary_total, 2),
                'payment_method': 'Наличные' if order.payment_method == 'cash' else 'Безнал',
            })

        return report

    def get_masters_report(self, date_from: datetime, date_to: datetime):
        """
        Сводка по мастерам за период: сколько нарядов и сколько заработано.
        """
        orders = self.db.query(WorkOrder).filter(
            WorkOrder.paid_at >= date_from,
            WorkOrder.paid_at <= date_to,
            WorkOrder.status == 'paid',
            WorkOrder.is_deleted == False
        ).all()

        salaries = self._salary_by_order([o.id for o in orders])
        totals = {}

        for order in orders:
            for entry in salaries.get(order.id, []):
                master = totals.setdefault(entry['employee_id'], {
                    'employee_id': entry['employee_id'],
                    'orders': 0,
                    'salary': 0.0,
                    'revenue': 0.0,
                })
                master['orders'] += 1
                master['salary'] += entry['amount']
                master['revenue'] += float(order.total_amount or 0)

        result = list(totals.values())
        for master in result:
            master['salary'] = round(master['salary'], 2)
            master['revenue'] = round(master['revenue'], 2)

        result.sort(key=lambda m: m['salary'], reverse=True)
        return result


    def get_duration_accuracy(self, min_orders: int = 5):
        """
        Насколько нормативы времени совпадают с реальностью.

        Первоначальные длительности услуг ставятся на глаз, и это нормально:
        по накопленным фактическим замерам видно, где норматив занижен.
        Наряды с одной услугой дают самую чистую оценку по этой услуге.

        Возвращает список услуг, у которых накопилось не меньше min_orders
        замеров, с плановым и фактическим средним временем.
        """
        from models import WorkOrderItem, Service
        from services.order_service import OrderService
        from services.settings_service import SettingsService

        # Базовое время (приём, оформление, заезд и выезд) тратится один раз
        # на наряд, а не на каждое колесо. Если его не вычесть, норматив
        # на единицу услуги окажется завышенным.
        base_minutes = SettingsService(self.db).get_int('order_base_minutes')

        orders = self.db.query(WorkOrder).filter(
            WorkOrder.started_at.isnot(None),
            WorkOrder.finished_at.isnot(None),
            WorkOrder.is_deleted == False
        ).all()

        # {service_id: [фактические минуты, ...]}
        measurements = {}

        for order in orders:
            items = self.db.query(WorkOrderItem).filter_by(work_order_id=order.id).all()
            # Берём только наряды из одной услуги: иначе непонятно,
            # какая из работ съела время
            if len(items) != 1:
                continue

            actual = OrderService.actual_minutes(order)
            if actual is None or actual <= 0:
                continue

            # Чистое время работы, без приёмки и оформления
            work_minutes = actual - base_minutes
            if work_minutes <= 0:
                continue

            item = items[0]
            per_unit = work_minutes / max(1, item.quantity)
            measurements.setdefault(item.service_id, []).append(per_unit)

        result = []
        for service_id, values in measurements.items():
            if len(values) < min_orders:
                continue
            service = self.db.query(Service).filter(Service.id == service_id).first()
            if not service:
                continue

            average = sum(values) / len(values)
            planned = service.duration_minutes or 0
            result.append({
                'service': service.name,
                'service_id': service_id,
                'planned_minutes': planned,
                'actual_minutes': round(average),
                'measurements': len(values),
                'difference': round(average) - planned,
            })

        # Сначала те, где расхождение больше — их и стоит поправить
        result.sort(key=lambda row: abs(row['difference']), reverse=True)
        return result

    def get_sales_statistics(self, date_from: datetime, date_to: datetime):
        """
        Расчёт статистики продаж за период
        
        Args:
            date_from: Начало периода
            date_to: Конец периода
        
        Returns:
            dict: {
                'total_cars': int,  # Количество машин
                'total_services': int,  # Всего услуг
                'total_revenue': float,  # Общая выручка
                'average_check': float,  # Средний чек
                'services': [  # Список услуг с детализацией
                    {
                        'name': str,  # Название услуги
                        'count': int,  # Количество оказанных услуг
                        'revenue': float  # Выручка по услуге
                    },
                    ...
                ]
            }
        """
        # Получаем все неудалённые оплаченные наряды за период
        orders = self.db.query(WorkOrder).filter(
            WorkOrder.paid_at >= date_from,
            WorkOrder.paid_at <= date_to,
            WorkOrder.status == 'paid',
            WorkOrder.is_deleted == False  # Исключаем удалённые
        ).all()
        
        # Словарь для сбора статистики по услугам
        # {service_name: {'count': количество, 'revenue': выручка}}
        services_stats = {}
        
        # Проходим по всем нарядам и собираем услуги
        for order in orders:
            items = self.db.query(WorkOrderItem).filter_by(
                work_order_id=order.id
            ).all()
            
            # Рассчитываем промежуточную сумму теми же функциями, что касса
            from services.order_service import OrderService
            subtotal = sum(OrderService.item_total(item) for item in items)
            
            # Коэффициент для пропорционального распределения итоговой суммы наряда
            # (с учётом общих скидок) между услугами
            ratio = float(order.total_amount) / subtotal if subtotal > 0 else 0
            
            for item in items:
                service_name = item.service.name
                
                # Рассчитываем стоимость услуги со скидкой по позиции
                item_subtotal = OrderService.item_total(item)
                
                # Применяем коэффициент для учёта общей скидки на наряд
                item_total = item_subtotal * ratio
                
                # Добавляем в статистику
                if service_name not in services_stats:
                    services_stats[service_name] = {'count': 0, 'revenue': 0.0,
                                                    'consumables': 0.0}

                services_stats[service_name]['count'] += item.quantity
                services_stats[service_name]['revenue'] += item_total
                # Материалы по этой услуге — из снимка себестоимости в позиции
                services_stats[service_name]['consumables'] += OrderService.item_consumables(item)

        # Считаем общую статистику - используем ГОТОВЫЙ total_amount из нарядов
        total_cars = len(orders)
        total_services = sum(s['count'] for s in services_stats.values())

        # Возвраты вычитаем из выручки, гарантийные переделки в неё
        # не входят вовсе: это бесплатный повторный визит по нашей вине
        total_refunds = sum(float(order.refunded_amount or 0) for order in orders)
        warranty_orders = [o for o in orders if o.is_warranty]

        gross = sum(float(order.total_amount) for order in orders)
        total_revenue = gross - total_refunds

        # Средний чек считаем по платным нарядам: гарантийные и полностью
        # возвращённые его занижали бы
        paying = [o for o in orders
                  if not o.is_warranty
                  and float(o.total_amount or 0) - float(o.refunded_amount or 0) > 0]
        average_check = (sum(float(o.total_amount or 0) - float(o.refunded_amount or 0)
                             for o in paying) / len(paying)) if paying else 0

        # Расходники и зарплата: что из выручки ушло на материалы и мастеров
        total_consumables = sum(float(order.consumables_amount or 0) for order in orders)

        salaries = self._salary_by_order([o.id for o in orders])
        total_salary = sum(entry['amount']
                           for entries in salaries.values() for entry in entries)

        # Маржа — то, что остаётся шиномонтажу после материалов и зарплаты
        margin = total_revenue - total_consumables - total_salary

        # Формируем список услуг, отсортированный по выручке (самые прибыльные сверху)
        services_list = [
            {
                'name': name,
                'count': data['count'],
                'revenue': round(data['revenue'], 2),
                'consumables': round(data['consumables'], 2),
                # По услуге маржа считается без зарплаты: она начисляется
                # с наряда целиком и по услугам не делится
                'margin': round(data['revenue'] - data['consumables'], 2),
            }
            for name, data in services_stats.items()
        ]
        services_list.sort(key=lambda x: x['revenue'], reverse=True)
        
        return {
            'total_cars': total_cars,
            'total_services': total_services,
            'total_revenue': round(total_revenue, 2),
            'total_consumables': round(total_consumables, 2),
            'total_salary': round(total_salary, 2),
            'total_refunds': round(total_refunds, 2),
            'warranty_count': len(warranty_orders),
            'margin': round(margin, 2),
            'average_check': round(average_check, 2),
            'services': services_list
        }
