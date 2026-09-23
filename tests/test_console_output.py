"""
Программа не падает из-за кодировки консоли.

Собранный .exe умирал при запуске: в отладочных сообщениях есть символы
«✓», «⚠», «₽», а консоль Windows работает в cp1251. Печать такого символа
выбрасывала UnicodeEncodeError, обработчик ошибки печатал «✗» и падал
следом — окно программы даже не появлялось.
"""
import _setup
from _setup import check, finish

import os
import subprocess
import sys

SYMBOLS = "✓ ✗ ⚠ ❌ 💾 ₽ №"

# Запускаем в отдельном процессе с русской кодировкой консоли,
# как это происходит на компьютере в шиномонтаже
CP1251_ENV = dict(os.environ, PYTHONIOENCODING='cp1251')


def run_snippet(code, reads_utf8=False):
    """
    Выполнить код в отдельном процессе с русской кодировкой консоли.

    reads_utf8=True — если код вызывает make_output_safe(): после неё
    процесс пишет в UTF-8, и читать его вывод надо соответственно.
    """
    encoding = 'utf-8' if reads_utf8 else 'cp1251'
    return subprocess.run([sys.executable, '-c', code], capture_output=True,
                          text=True, encoding=encoding, errors='replace',
                          env=CP1251_ENV, cwd=_setup.PROJECT_DIR)


print('=== Без защиты печать таких символов роняет процесс ===')
result = run_snippet(f'print("{SYMBOLS}")')
check('падает с UnicodeEncodeError',
      result.returncode != 0 and 'UnicodeEncodeError' in result.stderr,
      (result.stderr or '').strip()[-120:])

print('\n=== С защитой печатает без падения ===')
result = run_snippet(
    'import sys; sys.path.insert(0, r"%s")\n'
    'from utils import make_output_safe\n'
    'make_output_safe()\n'
    'print("%s")\n'
    'print("готово")' % (_setup.PROJECT_DIR, SYMBOLS),
    reads_utf8=True
)
check('процесс не упал', result.returncode == 0, (result.stderr or '').strip()[-200:])
check('вывод дошёл до конца', 'готово' in (result.stdout or ''),
      (result.stdout or '').strip()[-100:])

print('\n=== Отсутствующий поток вывода не мешает ===')
# В оконном режиме PyInstaller потоков вывода может не быть вовсе
result = run_snippet(
    'import sys; sys.path.insert(0, r"%s")\n'
    'from utils import make_output_safe\n'
    'sys.stdout = None; sys.stderr = None\n'
    'make_output_safe()\n'
    'sys.stderr = sys.__stderr__\n'
    'sys.stderr.write("ok")' % _setup.PROJECT_DIR
)
check('без потоков вывода не падает', result.returncode == 0,
      (result.stderr or '').strip()[-200:])

print('\n=== Сообщения о шрифте из чекового модуля ===')
# Именно на этих строках падал собранный .exe
result = run_snippet(
    'import sys; sys.path.insert(0, r"%s")\n'
    'from utils import make_output_safe\n'
    'make_output_safe()\n'
    'from services.print_service import PrintService\n'
    'PrintService()\n'
    'print("модуль печати создан")' % _setup.PROJECT_DIR,
    reads_utf8=True
)
check('модуль печати создаётся в cp1251-консоли', result.returncode == 0,
      (result.stderr or '').strip()[-250:])
check('дошло до конца', 'модуль печати создан' in (result.stdout or ''),
      (result.stdout or '').strip()[-120:])

finish()
