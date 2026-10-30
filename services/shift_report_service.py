"""
Сводка по смене и автоматическое закрытие забытой смены.

Смену регулярно забывают закрыть: рабочий день кончился, программу
выключили. Утром её закрывает сама программа, считает итоги и
отправляет сводку владельцу в Telegram.
"""
from datetime import datetime, timedelta

from models import Shift, WorkOrder
from utils import get_moscow_time, as_naive
from logger import log

AUTOCLOSE_ENABLED_KEY = 'shift_autoclose_enabled'
AUTOCLOSE_TIME_KEY = 'shift_autoclose_time'
REPORT_TO_TELEGRAM_KEY = 'shift_report_to_telegram'


class ShiftReportService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Сводка
    # ------------------------------------------------------------------

    def build_summary(self, shift):
        """Собрать цифры по смене: наряды, выручка, материалы, зарплата."""
        from services.statistics_service import StatisticsService

        start = as_naive(shift.start_time)
        end = as_naive(shift.end_time) or get_moscow_time()

        orders = self.db.query(WorkOrder).filter(
            WorkOrder.shift_id == shift.id,
            WorkOrder.status == 'paid',
            WorkOrder.is_deleted == False
        ).all()

        # Если наряды к смене не привязаны (старые записи), берём по времени
        if not orders:
            orders = self.db.query(WorkOrder).filter(
                WorkOrder.paid_at >= start,
                WorkOrder.paid_at <= end,
                WorkOrder.status == 'paid',
                WorkOrder.is_deleted == False
            ).all()

        stats = StatisticsService(self.db)
        salaries = stats._salary_by_order([o.id for o in orders])

        by_master = {}
        for entries in salaries.values():
            for entry in entries:
                by_master[entry['employee_id']] = round(
                    by_master.get(entry['employee_id'], 0) + entry['amount'], 2)

        revenue = sum(float(o.total_amount or 0) for o in orders)
        # Возвраты, проведённые в эту смену (наряд мог быть и вчерашним) —
        # чтобы сводка сходилась с «Отчётами» (решение владельца 26.10.2026)
        refunded_orders = self.db.query(WorkOrder).filter(
            WorkOrder.refunded_at.isnot(None), WorkOrder.is_deleted == False).all()
        refunds = sum(float(o.refunded_amount or 0) for o in refunded_orders
                      if start <= as_naive(o.refunded_at) <= as_naive(end))
        consumables = sum(float(o.consumables_amount or 0) for o in orders)
        salary_total = round(sum(by_master.values()), 2)

        cash = sum(o.cash_part for o in orders)
        card = revenue - cash

        duration = (as_naive(end) - start).total_seconds() / 3600 if start else 0

        # Выручка по направлениям — по строкам: наряд бывает «и то и то».
        # Строки считаем до общих округлений и пересчитываем в доли от
        # итога наряда, чтобы сумма направлений совпала с выручкой
        from services.order_service import OrderService
        by_direction = {}
        for o in orders:
            items = [i for i in o.items]
            lines_total = sum(OrderService.item_total(i) for i in items) or 0
            for i in items:
                share = (OrderService.item_total(i) / lines_total * float(o.total_amount or 0)
                         if lines_total else 0)
                key = getattr(i, 'direction', None) or 'tire'
                by_direction[key] = round(by_direction.get(key, 0) + share, 2)

        return {
            'shift': shift,
            'start': start,
            'end': end,
            'duration_hours': round(duration, 1),
            'orders_count': len(orders),
            'revenue': round(revenue, 2),
            'refunds': round(refunds, 2),
            'net_revenue': round(revenue - refunds, 2),
            'cash': round(cash, 2),
            'card': round(card, 2),
            'consumables': round(consumables, 2),
            'salary_total': salary_total,
            'by_master': by_master,
            'margin': round(revenue - refunds - consumables - salary_total, 2),
            'average_check': round(revenue / len(orders), 2) if orders else 0,
            'by_direction': by_direction,
        }

    def format_summary(self, summary):
        """Текст сводки для отправки в мессенджер."""
        shift = summary['shift']
        start = summary['start'].strftime('%d.%m.%Y %H:%M') if summary['start'] else '—'
        end = summary['end'].strftime('%d.%m.%Y %H:%M') if summary['end'] else '—'

        lines = [
            f"<b>Смена №{shift.id} закрыта</b>",
            f"{start} — {end}  ({summary['duration_hours']} ч)",
            f"Постов: {shift.open_posts}",
            "",
            f"Обслужено машин: <b>{summary['orders_count']}</b>",
            f"Выручка: <b>{summary['revenue']:.0f} ₽</b>",
            f"  наличные: {summary['cash']:.0f} ₽",
            f"  безнал: {summary['card']:.0f} ₽",
        ]
        # Возвраты — отдельной строкой и итог: так сводка сходится с «Отчётами»
        if summary.get('refunds'):
            lines += [f"Возвраты: −{summary['refunds']:.0f} ₽",
                      f"Итого: <b>{summary['net_revenue']:.0f} ₽</b>"]
        lines += [
            f"Средний чек: {summary['average_check']:.0f} ₽",
        ]
        # Мойка работает — выручку показываем и по направлениям
        if summary.get('by_direction', {}).get('wash'):
            lines += [f"  шиномонтаж: {summary['by_direction'].get('tire', 0):.0f} ₽",
                      f"  мойка: {summary['by_direction'].get('wash', 0):.0f} ₽"]
        lines += [
            "",
            f"Расходники: {summary['consumables']:.0f} ₽",
            f"Зарплата: {summary['salary_total']:.0f} ₽",
        ]

        if summary['by_master']:
            # По имени, а не «мастер №1»: владелец читает сводку с
            # телефона и номеров мастеров не помнит
            from models import Employee
            people = {row.id: row for row in self.db.query(Employee).filter(
                Employee.id.in_(list(summary['by_master']))).all()}
            for employee_id, amount in sorted(summary['by_master'].items()):
                person = people.get(employee_id)
                who = person.title if person is not None else f"мастер №{employee_id}"
                lines.append(f"  {who}: {amount:.0f} ₽")

        lines += ["", f"Осталось шиномонтажу: <b>{summary['margin']:.0f} ₽</b>"]
        try:
            from services.cash_service import CashService
            lines += CashService(self.db).summary_lines(shift)
        except Exception:
            self.db.rollback()
        return "\n".join(lines)

    def send_summary(self, shift, on_done=None):
        """Отправить сводку по смене в Telegram, не блокируя интерфейс."""
        from services.settings_service import SettingsService
        from services.telegram_service import TelegramService

        settings = SettingsService(self.db)
        if settings.get(REPORT_TO_TELEGRAM_KEY, '1') != '1':
            return False

        telegram = TelegramService(self.db)
        if not telegram.is_configured('shift'):
            log.info("Сводка по смене не отправлена: Telegram не настроен")
            return False

        text = self.format_summary(self.build_summary(shift))
        telegram.send_async(lambda: telegram.send_message(text, kind='shift'), on_done=on_done)
        return True

    # ------------------------------------------------------------------
    # Автозакрытие
    # ------------------------------------------------------------------

    def get_autoclose_time(self):
        """Час и минута автозакрытия из настроек."""
        from services.settings_service import SettingsService

        raw = SettingsService(self.db).get(AUTOCLOSE_TIME_KEY, '09:05') or '09:05'
        try:
            hours, minutes = raw.split(':')
            return int(hours), int(minutes)
        except (ValueError, AttributeError):
            return 9, 5

    def is_autoclose_enabled(self):
        from services.settings_service import SettingsService
        return SettingsService(self.db).get(AUTOCLOSE_ENABLED_KEY, '1') == '1'

    def find_overdue_shift(self, now=None):
        """
        Найти смену, которую пора закрыть.

        Правило владельца 27.10.2026: смена закрывается каждое утро в
        9:05, когда бы её ни открыли, — в ближайшие 9:05 после открытия.
        Открыли меньше чем за час до них (закрыли вручную и открыли снова
        в 9:02) — до следующего утра: закрывать её через три минуты
        было бы издевательством.
        """
        if not self.is_autoclose_enabled():
            return None

        now = as_naive(now or get_moscow_time())
        hours, minutes = self.get_autoclose_time()

        shift = self.db.query(Shift).filter(Shift.status == 'open').first()
        if not shift:
            return None

        start = as_naive(shift.start_time)
        if not start:
            return None

        # Момент автозакрытия — ближайшее заданное время после открытия
        deadline = datetime(start.year, start.month, start.day, hours, minutes)
        if deadline - start < timedelta(hours=1):
            deadline += timedelta(days=1)

        return shift if now >= deadline else None

    def autoclose_if_needed(self, now=None, on_report_sent=None):
        """
        Закрыть забытую смену и отправить сводку.

        Возвращает закрытую смену или None, если закрывать нечего.
        """
        shift = self.find_overdue_shift(now)
        if not shift:
            return None

        from services.shift_service import ShiftService
        from services.audit_service import AuditService

        try:
            ShiftService(self.db).close_shift(shift.id)
            self.db.refresh(shift)

            AuditService(self.db).log(
                'shift.autoclose',
                f"Смена №{shift.id} закрыта автоматически: её забыли закрыть вручную",
                entity_type='shift', entity_id=shift.id)

            self.send_summary(shift, on_done=on_report_sent)
            return shift
        except Exception as e:
            self.db.rollback()
            log.error(f"Не удалось автоматически закрыть смену: {e}")
            return None
