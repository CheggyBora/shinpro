"""
Сервис для расчёта статистики продаж
"""
from datetime import datetime
from models import WorkOrder, WorkOrderItem
from sqlalchemy import func

class StatisticsService:
    def __init__(self, db):
        self.db = db
    
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
            
            # Рассчитываем промежуточную сумму без общих скидок
            subtotal = sum(float(item.price) * item.quantity * (1 - item.discount_percent / 100) for item in items)
            
            # Коэффициент для пропорционального распределения итоговой суммы наряда
            # (с учётом общих скидок) между услугами
            ratio = float(order.total_amount) / subtotal if subtotal > 0 else 0
            
            for item in items:
                service_name = item.service.name
                
                # Рассчитываем стоимость услуги без общей скидки
                item_subtotal = float(item.price) * item.quantity * (1 - item.discount_percent / 100)
                
                # Применяем коэффициент для учёта общей скидки на наряд
                item_total = item_subtotal * ratio
                
                # Добавляем в статистику
                if service_name not in services_stats:
                    services_stats[service_name] = {'count': 0, 'revenue': 0.0}
                
                services_stats[service_name]['count'] += item.quantity
                services_stats[service_name]['revenue'] += item_total
        
        # Считаем общую статистику - используем ГОТОВЫЙ total_amount из нарядов
        total_cars = len(orders)
        total_services = sum(s['count'] for s in services_stats.values())
        total_revenue = sum(float(order.total_amount) for order in orders)  # Используем готовую сумму!
        average_check = total_revenue / total_cars if total_cars > 0 else 0
        
        # Формируем список услуг, отсортированный по выручке (самые прибыльные сверху)
        services_list = [
            {
                'name': name,
                'count': data['count'],
                'revenue': round(data['revenue'], 2)
            }
            for name, data in services_stats.items()
        ]
        services_list.sort(key=lambda x: x['revenue'], reverse=True)
        
        return {
            'total_cars': total_cars,
            'total_services': total_services,
            'total_revenue': round(total_revenue, 2),
            'average_check': round(average_check, 2),
            'services': services_list
        }
