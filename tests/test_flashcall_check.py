"""
Проверка ключа flashcall.ru пробным звонком (решение владельца 30.10.2026).

Сеть не трогаем: ответы сервиса подменены. Проверяем, что запрос
собран как в документации, ошибки понятны человеку, а окно доводит
проверку до «всё работает» или «звонка не было».
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('flashcall_check')

import io
import json
import urllib.error

from services import flashcall

sent = []


class Answer:
    def __init__(self, body):
        self.body = json.dumps(body).encode('utf-8')

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake(responses):
    def urlopen(request, timeout=None):
        sent.append(request)
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return Answer(result)
    flashcall.urllib.request.urlopen = urlopen


print('=== Номер ===')
check('8 909 … → +7909…', flashcall.e164('8 (909) 901-89-31') == '+79099018931')
try:
    flashcall.e164('123')
    check('короткий номер — ошибка', False)
except flashcall.FlashcallError as e:
    check('короткий номер — понятная ошибка', '11 цифр' in str(e))

print('\n=== Номер для звонка ===')
fake([{'id': 'c1x8', 'phone': '+74950000000', 'expiresIn': 60}])
check_id, dial, seconds = flashcall.get_phone('KEY', '+7 909 901-89-31')
body = json.loads(sent[-1].data.decode('utf-8'))
check('запрос как в документации', sent[-1].full_url.endswith('/api/v1/get-phone')
      and body == {'token': 'KEY', 'phone': '+79099018931'}, str(body))
check('ответ разобран', (check_id, dial, seconds) == ('c1x8', '+74950000000', 60))

fake([urllib.error.HTTPError('u', 401, 'bad', {}, io.BytesIO(b'{"message": "invalid token"}'))])
try:
    flashcall.get_phone('WRONG', '+79099018931')
    check('неверный ключ — ошибка', False)
except flashcall.FlashcallError as e:
    check('неверный ключ — «не принят»', 'не принят' in str(e) and 'invalid token' in str(e), str(e))

fake([urllib.error.URLError('нет сети')])
try:
    flashcall.get_phone('KEY', '+79099018931')
except flashcall.FlashcallError as e:
    check('нет интернета — так и сказано', 'интернет' in str(e), str(e))

print('\n=== Состояние ===')
fake([{'status': 'PENDING'}, {'status': 'CONFIRMED', 'callerPhone': '+79099018931'},
      {'status': 'EXPIRED'}])
check('ждём', flashcall.status('KEY', 'c1x8')[0] == flashcall.PENDING)
check('query: token и id', 'token=KEY' in sent[-1].full_url and 'id=c1x8' in sent[-1].full_url)
check('подтверждён, с какого номера', flashcall.status('KEY', 'c1x8') ==
      (flashcall.CONFIRMED, '+79099018931'))
check('звонка не было', flashcall.status('KEY', 'c1x8')[0] == flashcall.EXPIRED)

print('\n=== Окно проверки ===')
import tkinter as tk
import styles
import ui.call_key_check as screen

root = tk.Tk()
root.geometry('+-3000+0')
styles.apply_modern_styles(root)
screen.POLL_MS = 50
fake([{'id': 'c2', 'phone': '+74950000001', 'expiresIn': 60},
      {'status': 'PENDING'}, {'status': 'CONFIRMED', 'callerPhone': '+79099018931'}])
window = screen.CallKeyCheck(root, 'KEY', '+7 909 901-89-31')
window.start()
for _ in range(60):
    root.update()
    root.after(20)
    if 'работает' in window.state.cget('text'):
        break
check('номер для звонка показан', window.dial.cget('text') == '+74950000001')
check('дошло до «всё работает»', 'Всё работает' in window.state.cget('text'),
      window.state.cget('text'))
window.close()

fake([urllib.error.HTTPError('u', 401, 'bad', {}, io.BytesIO(b'{}'))])
window = screen.CallKeyCheck(root, 'WRONG', '+7 909 901-89-31')
window.start()
for _ in range(40):
    root.update()
    root.after(20)
    if '✗' in window.state.cget('text'):
        break
check('неверный ключ — в окне так и написано', 'не принят' in window.state.cget('text'),
      window.state.cget('text'))
window.close()
root.destroy()

finish()
