"""
Планирование времени: длительности услуг, посты, «Сохранить наряд».

Главное здесь — время в очереди НЕ должно меняться, пока мастер
прикидывает стоимость. Он забивает услугу, чтобы назвать цену, клиент
отказывается, услуга убирается — и так по кругу. Раньше от этого прогноз
для всех ожидающих скакал бы туда-сюда.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('planning')

from config import init_db, SessionLocal
from models import Service, Car
from services import OrderService, SalaryService, EmployeeService
from services.shift_service import ShiftService
from services.settings_service import SettingsService
from services.statistics_service import StatisticsService

init_db()
db = SessionLocal()

settings = SettingsService(db)
settings.ensure_defaults()

shift_service = ShiftService(db)
order_service = OrderService(db)
emp = EmployeeService(db)

print('=== Посты в смене ===')
shift = shift_service.open_shift(open_posts=3)
check('в смене открыто 3 поста', shift.open_posts == 3, str(shift.open_posts))

shift_service.set_open_posts(shift.id, 2)
db.refresh(shift)
check('число постов меняется посреди смены', shift.open_posts == 2, str(shift.open_posts))

try:
    shift_service.set_open_posts(shift.id, 0)
    check('ноль постов отклоняется', False, 'принято')
except ValueError as e:
    check('ноль постов отклоняется', True, str(e))

emp.register_employee(1)
emp.start_shift(1)

db.add(Service(name='Перекидка колеса', vehicle_type='car', price_r16=300.0, duration_minutes=5))
db.add(Service(name='Переобувка колеса', vehicle_type='car', price_r16=700.0, duration_minutes=15))
db.add(Service(name='Правка диска', vehicle_type='car', price_r16=2000.0, duration_minutes=30))
db.commit()
services = {s.name: s for s in db.query(Service).all()}

print('\n=== Время наряда ===')
check('базовое время наряда 10 мин', settings.get_int('order_base_minutes') == 10)

order = order_service.create_order('А123ВВ777', 'R16', 'car')
check('пустой наряд — только базовое время',
      order_service.calculate_planned_minutes(order.id) == 10,
      str(order_service.calculate_planned_minutes(order.id)))

item = order_service.add_service_to_order(order.id, services['Перекидка колеса'].id)
order_service.update_item_full(item.id, 4, item.price, item.discount_percent)
check('10 + 5 x 4 = 30 мин',
      order_service.calculate_planned_minutes(order.id) == 30,
      str(order_service.calculate_planned_minutes(order.id)))

print('\n=== Пока не сохранили — время очереди не меняется ===')
check('плановое время ещё ноль', (order.planned_minutes or 0) == 0, str(order.planned_minutes))
check('программа видит несохранённые изменения',
      order_service.has_unsaved_time_changes(order.id) is True)

saved = order_service.save_order_composition(order.id)
db.refresh(order)
check('после сохранения плановое время 30', saved == 30 and order.planned_minutes == 30,
      str(order.planned_minutes))
check('несохранённых изменений больше нет',
      order_service.has_unsaved_time_changes(order.id) is False)

print('\n=== Мастер прикидывает цену — время не скачет ===')
# Мастер забил правку диска, чтобы озвучить стоимость
probe = order_service.add_service_to_order(order.id, services['Правка диска'].id)
db.refresh(order)
check('расчётное время выросло до 60', order_service.calculate_planned_minutes(order.id) == 60)
check('но плановое осталось 30', order.planned_minutes == 30, str(order.planned_minutes))
check('видно, что есть несохранённое', order_service.has_unsaved_time_changes(order.id) is True)

# Клиент отказался
order_service.delete_item(probe.id)
db.refresh(order)
check('после отказа расчётное вернулось к 30',
      order_service.calculate_planned_minutes(order.id) == 30)
check('плановое так и не дёрнулось', order.planned_minutes == 30, str(order.planned_minutes))
check('несохранённых изменений снова нет',
      order_service.has_unsaved_time_changes(order.id) is False)

print('\n=== Согласованная допуслуга меняет время один раз ===')
order_service.add_service_to_order(order.id, services['Правка диска'].id)
order_service.save_order_composition(order.id)
db.refresh(order)
check('после согласования плановое время 60', order.planned_minutes == 60,
      str(order.planned_minutes))

print('\n=== Взятие в работу согласовывает состав разом ===')
# Берём другую услугу, чтобы этот наряд не смешивался с замерами
# для отчёта «норматив против факта» ниже
order2 = order_service.create_order('К900ОР99', 'R16', 'car')
i2 = order_service.add_service_to_order(order2.id, services['Перекидка колеса'].id)
order_service.update_item_full(i2.id, 4, i2.price, i2.discount_percent)
check('до начала работ плановое время ноль', (order2.planned_minutes or 0) == 0)

order_service.start_work(order2.id)
db.refresh(order2)
check('«в работу» зафиксировало 10 + 5 x 4 = 30 мин', order2.planned_minutes == 30,
      str(order2.planned_minutes))
check('время начала работ записано', order2.started_at is not None)

print('\n=== Пауза не засчитывается в фактическое время ===')
from datetime import timedelta
from utils import as_naive

order_service.pause_work(order2.id)
db.refresh(order2)
check('пауза зафиксирована', order2.paused_at is not None)

# Отматываем начало паузы на 20 минут назад, как будто ждали деталь
order2.paused_at = as_naive(order2.paused_at) - timedelta(minutes=20)
db.commit()

order_service.resume_work(order2.id)
db.refresh(order2)
check('простой учтён (20 мин)', order2.paused_minutes >= 19, str(order2.paused_minutes))
check('пауза снята', order2.paused_at is None)

# Отматываем начало работ на час назад
order2.started_at = as_naive(order2.started_at) - timedelta(minutes=60)
db.commit()
order_service.finish_work(order2.id)
db.refresh(order2)

actual = OrderService.actual_minutes(order2)
check('фактически 60 минут минус 20 паузы = около 40',
      38 <= actual <= 42, f'получено {actual}')

print('\n=== Колёса в сборе запоминаются за машиной ===')
order_service.create_order('Т777ТТ77', 'R16', 'car', wheels_assembled=True)
car = order_service.get_car_by_license_plate('Т777ТТ77')
check('признак сохранён', car.wheels_assembled is True)

# Новый наряд без указания не должен затирать известное значение
order_service.create_order('Т777ТТ77', 'R16', 'car')
db.refresh(car)
check('повторный наряд без указания не стёр признак', car.wheels_assembled is True)

order_service.create_order('Т777ТТ77', 'R16', 'car', wheels_assembled=False)
db.refresh(car)
check('явное указание меняет признак', car.wheels_assembled is False)

print('\n=== Отчёт «норматив против факта» ===')
# Пять нарядов из одной услуги. Каждый занял 35 минут: 10 базовых
# на приём и оформление плюс 25 минут работы при нормативе 15.
for n in range(5):
    o = order_service.create_order(f'Н{n}00НН77', 'R16', 'car')
    order_service.add_service_to_order(o.id, services['Переобувка колеса'].id)
    order_service.start_work(o.id)
    db.refresh(o)
    o.started_at = as_naive(o.started_at) - timedelta(minutes=35)
    db.commit()
    order_service.finish_work(o.id)

accuracy = StatisticsService(db).get_duration_accuracy(min_orders=5)
row = next((r for r in accuracy if r['service'] == 'Переобувка колеса'), None)
check('услуга попала в отчёт', row is not None, str(accuracy))
if row:
    check('норматив 15 мин', row['planned_minutes'] == 15, str(row['planned_minutes']))
    check('факт около 25 мин', 23 <= row['actual_minutes'] <= 27, str(row['actual_minutes']))
    check('видно занижение норматива', row['difference'] > 0, str(row['difference']))

db.close()
finish()
