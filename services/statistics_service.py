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
        # Получаем все неудалённые наряды за период
        orders = self.db.query(WorkOrder).filter(
            WorkOrder.created_at >= date_from,
            WorkOrder.created_at <= date_to,
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
            
            for item in items:
                service_name = item.service.name
                
                # Рассчитываем итоговую стоимость с учётом количества и скидки
                item_total = item.price * item.quantity * (1 - item.discount_percent / 100)
                
                # Добавляем в статистику
                if service_name not in services_stats:
                    services_stats[service_name] = {'count': 0, 'revenue': 0.0}
                
                services_stats[service_name]['count'] += item.quantity
                services_stats[service_name]['revenue'] += item_total
        
        # Считаем общую статистику
        total_cars = len(orders)
        total_services = sum(s['count'] for s in services_stats.values())
        total_revenue = sum(s['revenue'] for s in services_stats.values())
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
