"""
Срочная досылка: важное уходит сразу, а не через десять минут.

Обмен ходит по расписанию, раз в десять минут. Для копий этого
достаточно, но часть изменений человек видит немедленно, и десять
минут ожидания выглядят поломкой: оплатили наряд — в дашборде нет
выручки; выключили приём записи — а люди ещё записываются.

Проверяем:

  · просьба доходит до того, кто умеет запускать обмен;
  · несколько просьб подряд дают одну отправку, а не три;
  · пока обмен идёт, новую не заводим;
  · упавший запуск не роняет то, из чего его позвали, — досылка
    ускоряет, но ничего не обязана;
  · события, после которых цех обязан выйти на связь, действительно
    её зовут.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('sync_nudge')

_setup.silence_dialogs()

from services import sync_nudge

print('=== Без запускающего просьба молча ничего не делает ===')
sync_nudge.set_runner(None)
check('ответили «нет»', sync_nudge.request('проверка') is False)

print()
print('=== Просьба доходит ===')
calls = []
sync_nudge.set_runner(lambda delay_ms, reason: calls.append((delay_ms, reason))
                      or True)

check('позвали', sync_nudge.request('наряд оплачен') is True)
check('один раз', len(calls) == 1, str(calls))
check('с задержкой, а не мгновенно',
      calls[0][0] == sync_nudge.DELAY_SECONDS * 1000, str(calls))
check('причина передана', calls[0][1] == 'наряд оплачен', str(calls))

print()
print('=== Падение запуска не ломает вызвавшего ===')


def broken(delay_ms, reason):
    raise RuntimeError('сеть отвалилась')


sync_nudge.set_runner(broken)
check('вернули «нет», а не исключение',
      sync_nudge.request('смена закрыта') is False)

print()
print('=== Пачкой, а не по событию ===')
# Пачку собирает главное окно: пока досылка отложена, следующие
# просьбы к ней присоединяются
import inspect

import ui.main_window as main_window

source = inspect.getsource(main_window.MainWindow.sync_soon_after)
check('повторную просьбу не заводим',
      'self.sync_soon is not None' in source, source)
check('и поверх идущего обмена тоже',
      'self.sync_running' in source, source)
check('обмен выключен — не ходим', 'is_enabled()' in source, source)

print()
print('=== События, после которых надо выйти на связь ===')
WATCHED = [
    ('services/salary_service.py', 'наряд оплачен'),
    ('services/shift_service.py', 'смена открыта'),
    ('services/shift_service.py', 'изменилось число постов'),
    ('services/shift_service.py', 'смена закрыта'),
    ('services/tire_storage_service.py', 'приняли комплект на хранение'),
    ('services/tire_storage_service.py', 'выдали комплект'),
    ('ui/settings_dialog.py', 'изменены настройки'),
]

import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

for path, reason in WATCHED:
    text = io.open(os.path.join(ROOT, path), encoding='utf-8').read()
    check(f"{reason} → обмен", f"sync_nudge.request('{reason}')" in text)

sync_nudge.set_runner(None)
finish()
