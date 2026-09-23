#!/usr/bin/env python3
"""
Прогнать все тесты.

    python tests/run_all.py

Каждый тест запускается отдельным процессом: они работают с разными
временными базами, а config.py читает адрес базы один раз при импорте.
"""
import os
import subprocess
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

TESTS = [
    ('Нормализация номеров и телефонов', 'test_normalization.py'),
    ('Время смены и защита от двойной оплаты', 'test_timezone_and_payment.py'),
    ('Клиенты, машины и поиск', 'test_clients.py'),
    ('Арифметика чека', 'test_receipt_math.py'),
    ('Расходники и база для зарплаты', 'test_consumables.py'),
    ('Имена сотрудников и разбор начислений', 'test_employee_names.py'),
    ('Выдача зарплаты и ведомость', 'test_payout.py'),
    ('Экран выдачи зарплаты', 'test_payout_ui.py'),
    ('Планирование времени и посты', 'test_planning.py'),
    ('Скидка на отдельную услугу', 'test_item_discount.py'),
    ('Запись клиентов', 'test_appointments.py'),
    ('Посты записи и лента времени', 'test_booking.py'),
    ('Экран записи', 'test_booking_ui.py'),
    ('Обмен с сервером приложения', 'test_sync.py'),
    ('Записи через сервер', 'test_booking_remote.py'),
    ('Отчёты и выгрузка', 'test_reports.py'),
    ('Сводка по смене и Telegram', 'test_shift_report.py'),
    ('Рекомендации мастера', 'test_recommendations.py'),
    ('Возврат, сторно, гарантия', 'test_refund.py'),
    ('Наклейки и термочек', 'test_labels.py'),
    ('Реквизиты, кнопки услуг, журнал, получатели', 'test_tech_debt.py'),
    ('Окно настроек и порядок кнопок', 'test_settings_ui.py'),
    ('PIN-код и журнал действий', 'test_auth_and_audit.py'),
    ('Хранение шин', 'test_tire_storage.py'),
    ('Резервное копирование базы', 'test_backup.py'),
    ('Запуск программы при открытой смене', 'test_app_starts.py'),
    ('Экран администратора', 'test_admin_ui.py'),
    ('Интерфейс наряда', 'test_order_ui.py'),
    ('Клиенты и карточка клиента', 'test_clients_tab.py'),
    ('Миграция базы', 'test_migration.py'),
    ('Очистка рабочих данных', 'test_clear_data.py'),
    ('Устойчивость к кодировке консоли', 'test_console_output.py'),
]


def main():
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    results = []

    for title, filename in TESTS:
        print('=' * 70)
        print(f'  {title}')
        print('=' * 70)

        result = subprocess.run(
            [sys.executable, os.path.join(TESTS_DIR, filename)],
            cwd=TESTS_DIR, env=env
        )
        results.append((title, result.returncode == 0))
        print()

    print('=' * 70)
    print('  ИТОГ')
    print('=' * 70)
    for title, ok in results:
        print(f"  {'OK   ' if ok else 'СБОЙ '} {title}")

    failed = [title for title, ok in results if not ok]
    if failed:
        print(f'\nПровалено наборов: {len(failed)} из {len(results)}')
        sys.exit(1)

    print(f'\nВсе наборы пройдены ({len(results)}).')


if __name__ == '__main__':
    main()
