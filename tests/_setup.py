"""
Общая подготовка для тестов.

Импортировать ПЕРВЫМ, до config и models: config.py читает DATABASE_URL
в момент импорта, поэтому переменную нужно выставить заранее.
"""
import os
import sys
import tempfile

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

# Журнал теста уводим во временную папку: рабочий logs/ рядом с программой
# не должен заполняться тестовыми записями
os.environ.setdefault('TIRE_SHOP_LOG_DIR',
                      os.path.join(tempfile.gettempdir(), 'tire_shop_test_logs'))

_failures = []


def use_temp_db(name):
    """
    Подготовить чистую временную базу для теста и вернуть путь к ней.

    Если файл занят (например, остался от прерванного запуска), берём
    соседнее имя, а не падаем.
    """
    base = os.path.join(tempfile.gettempdir(), f'tire_shop_test_{name}')

    for attempt in range(10):
        path = f'{base}.db' if attempt == 0 else f'{base}_{attempt}.db'
        try:
            if os.path.exists(path):
                os.remove(path)
            os.environ['DATABASE_URL'] = f'sqlite:///{path}'
            return path
        except PermissionError:
            continue

    raise RuntimeError(f'Не удалось подготовить временную базу для теста «{name}»')


def silence_dialogs(*modules):
    """
    Заменить всплывающие окна на печать в консоль.

    Модальное окно messagebox ждёт нажатия кнопки и в тесте вешает процесс.
    Возвращает список показанных окон: (тип, заголовок, текст).
    """
    from tkinter import messagebox

    shown = []

    def make_stub(kind):
        def stub(title=None, message=None, **kwargs):
            shown.append((kind, title, message))
            print(f'    [окно {kind}] {title}: {str(message)[:150]}')
            return True if kind == 'askyesno' else 'ok'
        return stub

    for kind in ('showinfo', 'showwarning', 'showerror', 'askyesno'):
        stub = make_stub(kind)
        setattr(messagebox, kind, stub)
        for module in modules:
            if hasattr(module, 'messagebox'):
                setattr(module.messagebox, kind, stub)

    return shown


def check(name, condition, detail=''):
    """Проверка с понятным выводом. Копит провалы для финального отчёта."""
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f' -- {detail}' if detail else ''))
    if not condition:
        _failures.append(name)


def finish():
    """Завершить тест: код возврата 1, если хоть одна проверка провалилась."""
    print('-' * 60)
    if _failures:
        print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
        for item in _failures:
            print(f'  - {item}')
        sys.exit(1)
    print('Все проверки пройдены')
    sys.exit(0)
