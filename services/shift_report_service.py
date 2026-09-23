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
        consumables = sum(float(o.consumables_amount or 0) for o in orders)
        salary_total = round(sum(by_master.values()), 2)

        cash = sum(float(o.total_amount or 0) for o in orders if o.payment_method == 'cash')
        card = revenue - cash

        duration = (as_naive(end) - start).total_seconds() / 3600 if start else 0

        return {
            'shift': shift,
            'start': start,
            'end': end,
            'duration_hours': round(duration, 1),
            'orders_count': len(orders),
            'revenue': round(revenue, 2),
            'cash': round(cash, 2),
            'card': round(card, 2),
            'consumables': round(consumables, 2),
            'salary_total': salary_total,
            'by_master': by_master,
            'margin': round(revenue - consumables - salary_total, 2),
            'average_check': round(revenue / len(orders), 2) if orders else 0,
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
            f"Средний чек: {summary['average_check']:.0f} ₽",
            "",
            f"Расходники: {summary['consumables']:.0f} ₽",
            f"Зарплата: {summary['salary_total']:.0f} ₽",
        ]

        if summary['by_master']:
            for employee_id, amount in sorted(summary['by_master'].items()):
                lines.append(f"  мастер №{employee_id}: {amount:.0f} ₽")

        lines += ["", f"Осталось шиномонтажу: <b>{summary['margin']:.0f} ₽</b>"]
        return "\n".join(lines)

    def send_summary(self, shift, on_done=None):
        """Отправить сводку по смене в Telegram, не блокируя интерфейс."""
        from services.settings_service import SettingsService
        from services.telegram_service import TelegramService

        settings = SettingsService(self.db)
        if settings.get(REPORT_TO_TELEGRAM_KEY, '1') != '1':
            return False

        telegram = TelegramService(self.db)
        if not telegram.is_configured():
            log.info("Сводка по смене не отправлена: Telegram не настроен")
            return False

        text = self.format_summary(self.build_summary(shift))
        telegram.send_async(lambda: telegram.send_message(text), on_done=on_done)
        return True

    # ------------------------------------------------------------------
    # Автозакрытие
    # ------------------------------------------------------------------

    def get_autoclose_time(self):
        """Час и минута автозакрытия из настроек."""
        from services.settings_service import SettingsService

        raw = SettingsService(self.db).get(AUTOCLOSE_TIME_KEY, '09:00') or '09:00'
        try:
            hours, minutes = raw.split(':')
            return int(hours), int(minutes)
        except (ValueError, AttributeError):
            return 9, 0

    def is_autoclose_enabled(self):
        from services.settings_service import SettingsService
        return SettingsService(self.db).get(AUTOCLOSE_ENABLED_KEY, '1') == '1'

    def find_overdue_shift(self, now=None):
        """
        Найти смену, которую пора закрыть.

        Смена считается забытой, если она открыта и уже наступило время
        автозакрытия следующего календарного дня после её начала.
        Смену, открытую сегодня утром, не трогаем.
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

        # Момент автозакрытия — заданное время СЛЕДУЮЩЕГО дня после открытия
        deadline = datetime(start.year, start.month, start.day,
                            hours, minutes) + timedelta(days=1)

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
