#!/usr/bin/env python3
"""
Прогнать все тесты сервера.

    cd server && python tests/run_all.py

Каждый набор — отдельный процесс: они работают с разными временными
базами, а настройки читаются один раз при импорте.
"""
import os
import subprocess
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

TESTS = [
    ('Вход, запись, хранение, история, очередь', 'test_api.py'),
    ('Страница записи по ссылке', 'test_public.py'),
    ('Дашборд: вход персонала и права', 'test_staff.py'),
    ('Дашборд: выручка, мастера, наряды', 'test_dashboard.py'),
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
            cwd=os.path.dirname(TESTS_DIR), env=env)
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
