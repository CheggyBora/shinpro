"""
Отправка сообщений и файлов в Telegram.

Работает через бота: в настройках задаются токен бота и получатели —
владелец, бухгалтер, управляющий. Отчёт уходит всем включённым сразу.
Используется только стандартная библиотека Python — подключать
отдельный пакет ради двух запросов незачем.

Сбой у одного получателя не срывает отправку остальным: если у кого-то
бот заблокирован, другие всё равно получат отчёт.

Все отправки выполняются в отдельном потоке: интерфейс не должен
замирать, пока программа ждёт ответа от сети.
"""
import json
import mimetypes
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid

API_URL = 'https://api.telegram.org/bot{token}/{method}'

# Ждём ответ ограниченное время: при обрыве связи программа
# не должна зависать
TIMEOUT_SECONDS = 25

TOKEN_KEY = 'telegram_bot_token'
CHAT_KEY = 'telegram_chat_id'
RECIPIENTS_KEY = 'telegram_recipients'

# Докуда мы уже прочитали сообщения боту. Телеграм хранит их сутки и
# отдаёт по одному разу: не запомнив, где остановились, мы бы либо
# разбирали одно и то же, либо теряли тех, кто написал между заходами
OFFSET_KEY = 'telegram_updates_offset'


class TelegramError(Exception):
    pass


class Recipient:
    """
    Кому отправляем: имя для человека, номер чата для Telegram.

    Номер чата руками не вводят. Человек открывает бота, нажимает
    «Старт» — и появляется в списке сам. Раньше ему надо было найти
    бота @userinfobot, узнать там своё число и продиктовать его тому,
    кто сидит за компьютером: три действия и один шанс ошибиться
    цифрой, после чего сводка молча уходила в никуда.
    """

    def __init__(self, chat_id, name='', enabled=True, username=''):
        self.chat_id = str(chat_id or '').strip()
        self.name = (name or '').strip()
        self.enabled = bool(enabled)
        # Ник без «@», маленькими: по нему находим чат контрагента
        self.username = (username or '').strip().lstrip('@').lower()

    @property
    def title(self):
        return self.name or self.chat_id

    def to_dict(self):
        return {'chat_id': self.chat_id, 'name': self.name, 'enabled': self.enabled,
                'username': self.username}


class DeliveryResult:
    """
    Итог отправки нескольким получателям.

    Отдельный тип нужен, потому что «отправлено» перестало быть
    да/нет: часть получателей может не получить сообщение.
    """

    def __init__(self, delivered, failed):
        self.delivered = delivered          # список Recipient
        self.failed = failed                # список (Recipient, текст ошибки)

    @property
    def all_delivered(self):
        return bool(self.delivered) and not self.failed

    def summary(self):
        if not self.failed:
            if len(self.delivered) == 1:
                return "Отправлено в Telegram"
            return f"Отправлено в Telegram, получателей: {len(self.delivered)}"

        problems = '; '.join(f"{r.title} — {error}" for r, error in self.failed)
        if not self.delivered:
            return f"Не отправлено: {problems}"
        return (f"Отправлено получателям: {len(self.delivered)}. "
                f"Не дошло: {problems}")


class TelegramService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Настройки
    # ------------------------------------------------------------------

    def _settings(self):
        from services.settings_service import SettingsService
        return SettingsService(self.db)

    def get_token(self):
        return (self._settings().get(TOKEN_KEY, '') or '').strip()

    def get_chat_id(self):
        """
        Первый включённый получатель.

        Оставлено для мест, которым нужен один номер чата, и для настроек,
        сделанных до появления списка получателей.
        """
        active = self.get_active_recipients()
        if active:
            return active[0].chat_id
        return (self._settings().get(CHAT_KEY, '') or '').strip()

    def get_recipients(self):
        """
        Все получатели, включая выключенных.

        Если список ещё не заводили, а старый одиночный чат задан —
        показываем его как единственного получателя. Так настройки,
        сделанные до появления списка, продолжают работать.
        """
        raw = self._settings().get(RECIPIENTS_KEY, '') or ''
        recipients = []
        if raw.strip():
            try:
                for row in json.loads(raw):
                    recipient = Recipient(row.get('chat_id'), row.get('name'),
                                          row.get('enabled', True), row.get('username'))
                    if recipient.chat_id:
                        recipients.append(recipient)
            except (ValueError, TypeError, AttributeError):
                # Испорченный список не должен ломать отправку —
                # ниже подхватим старый одиночный чат
                recipients = []

        if recipients:
            return recipients

        legacy = (self._settings().get(CHAT_KEY, '') or '').strip()
        return [Recipient(legacy)] if legacy else []

    def chat_of(self, username):
        """Чат того, кто писал боту под этим ником. Не писал — None."""
        username = (username or '').strip().lstrip('@').lower()
        if not username:
            return None
        for recipient in self.get_recipients():
            if recipient.username == username:
                return recipient.chat_id
        return None

    def usernames(self):
        """{ник: чат} всех, кто писал боту, — серверу для задач из дашборда."""
        return {r.username: r.chat_id for r in self.get_recipients() if r.username}

    def get_active_recipients(self):
        return [r for r in self.get_recipients() if r.enabled and r.chat_id]

    def is_configured(self):
        return bool(self.get_token() and self.get_active_recipients())

    def save_recipients(self, recipients):
        """
        Сохранить список получателей.

        Первый включённый дублируется в старую настройку одиночного чата:
        так в базе не остаётся расхождения между двумя источниками.
        """
        settings = self._settings()
        rows = [r.to_dict() for r in recipients if r.chat_id]
        settings.set(RECIPIENTS_KEY, json.dumps(rows, ensure_ascii=False), commit=False)

        active = [r for r in recipients if r.enabled and r.chat_id]
        settings.set(CHAT_KEY, active[0].chat_id if active else '')

    # ------------------------------------------------------------------
    # Кто написал боту
    # ------------------------------------------------------------------

    def fetch_people(self):
        """
        Забрать у бота тех, кто ему написал, и добавить в список.

        Новых заводим **выключенными**: то, что человек нажал «Старт»,
        не значит, что ему нужна сводка по смене с выручкой. Кому
        отправлять — решает владелец галочкой.

        Возвращает (сколько новых, сколько всего написавших).
        """
        updates = self._call('getUpdates', {
            'offset': self._offset(),
            'timeout': 0,
            'allowed_updates': '["message"]',
        }) or []

        known = {r.chat_id: r for r in self.get_recipients()}
        order = self.get_recipients()
        added = 0
        seen = 0
        last = None

        for update in updates:
            last = update.get('update_id')
            message = update.get('message') or {}
            chat = message.get('chat') or {}
            chat_id = str(chat.get('id') or '').strip()
            if not chat_id:
                continue

            seen += 1
            name = _name_of(chat)
            username = chat.get('username') or ''

            if chat_id in known:
                # Имя могло появиться или смениться — подтянем, но
                # галочку «отправлять» не трогаем: её ставил человек
                if name and not known[chat_id].name:
                    known[chat_id].name = name
                if username:
                    known[chat_id].username = username.lower()
                continue

            fresh = Recipient(chat_id, name, enabled=False, username=username)
            order.append(fresh)
            known[chat_id] = fresh
            added += 1

        if last is not None:
            # +1, иначе телеграм отдаст то же самое ещё раз
            self._settings().set(OFFSET_KEY, last + 1, commit=False)

        self.save_recipients(order)
        return added, seen

    def _offset(self):
        try:
            return int(self._settings().get(OFFSET_KEY, 0) or 0)
        except (TypeError, ValueError):
            return 0

    def bot_link(self):
        """
        Ссылка на бота — её даём человеку, чтобы он нажал «Старт».

        Имя бота спрашиваем у телеграма: вводить его руками значит
        однажды ошибиться и отправить людей к чужому боту.
        """
        who = self._call('getMe', {}) or {}
        name = who.get('username')
        if not name:
            raise TelegramError('Телеграм не назвал имя бота')
        return f'https://t.me/{name}'

    def save_settings(self, token, chat_id):
        """Токен и один получатель — короткий путь для простого случая."""
        settings = self._settings()
        settings.set(TOKEN_KEY, (token or '').strip(), commit=False)

        chat_id = (chat_id or '').strip()
        if chat_id:
            self.save_recipients([Recipient(chat_id)])
        else:
            settings.set(RECIPIENTS_KEY, '', commit=False)
            settings.set(CHAT_KEY, '')

    def save_token(self, token):
        self._settings().set(TOKEN_KEY, (token or '').strip())

    # ------------------------------------------------------------------
    # Запросы
    # ------------------------------------------------------------------

    def _call(self, method, fields, files=None):
        """Выполнить запрос к боту. Возвращает разобранный ответ."""
        from config import offline_test_mode
        if offline_test_mode():
            raise TelegramError("Тестовый режим без связи")
        token = self.get_token()
        if not token:
            raise TelegramError("Не задан токен бота")

        url = API_URL.format(token=token, method=method)

        if files:
            body, content_type = _encode_multipart(fields, files)
            request = urllib.request.Request(url, data=body,
                                             headers={'Content-Type': content_type})
        else:
            body = urllib.parse.urlencode(fields).encode('utf-8')
            request = urllib.request.Request(url, data=body)

        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            detail = ''
            try:
                detail = json.loads(e.read().decode('utf-8')).get('description', '')
            except Exception:
                pass
            raise TelegramError(f"Telegram отклонил запрос: {detail or e}")
        except urllib.error.URLError as e:
            raise TelegramError(f"Нет связи с Telegram: {e.reason}")
        except Exception as e:
            raise TelegramError(f"Ошибка отправки: {e}")

        if not payload.get('ok'):
            raise TelegramError(payload.get('description', 'Telegram вернул ошибку'))

        return payload.get('result')

    def _send_to_all(self, build_call):
        """
        Разослать всем включённым получателям.

        Ошибка у одного получателя не прерывает рассылку: заблокировавший
        бота бухгалтер не должен лишать отчёта владельца. Исключение
        поднимаем только если не дошло вообще никому — тогда это не
        частная проблема получателя, а неверный токен или обрыв связи.
        """
        recipients = self.get_active_recipients()
        if not recipients:
            raise TelegramError("Telegram не настроен: укажите токен бота и получателя")

        delivered, failed = [], []
        for recipient in recipients:
            try:
                build_call(recipient)
                delivered.append(recipient)
            except TelegramError as e:
                failed.append((recipient, str(e)))
            except Exception as e:
                failed.append((recipient, f"неожиданная ошибка: {e}"))

        result = DeliveryResult(delivered, failed)
        if not delivered:
            raise TelegramError(result.summary())
        return result

    def send_message(self, text):
        """Отправить текстовое сообщение всем включённым получателям."""
        if not self.get_token():
            raise TelegramError("Не задан токен бота")

        def send(recipient):
            self._call('sendMessage', {
                'chat_id': recipient.chat_id,
                'text': text,
                'parse_mode': 'HTML',
                'disable_web_page_preview': 'true',
            })

        return self._send_to_all(send)

    def send_document(self, path, caption=None):
        """Отправить файл — например, выгруженный отчёт."""
        if not self.get_token():
            raise TelegramError("Не задан токен бота")

        if not os.path.exists(path):
            raise TelegramError(f"Файл не найден: {path}")

        # Читаем файл один раз, а не под каждого получателя
        with open(path, 'rb') as handle:
            content = handle.read()
        filename = os.path.basename(path)

        def send(recipient):
            fields = {'chat_id': recipient.chat_id}
            if caption:
                # Telegram ограничивает подпись к файлу
                fields['caption'] = caption[:1000]
            self._call('sendDocument', fields, files={'document': (filename, content)})

        return self._send_to_all(send)

    def test_connection(self):
        """
        Проверить, что бот отвечает и получатели доступны.

        Возвращает (имя бота, итог рассылки): по итогу видно, кому
        проверочное сообщение не дошло, — обычно это те, кто ещё не
        нажал боту «Старт».
        """
        info = self._call('getMe', {})
        result = self._send_to_all(lambda recipient: self._call('sendMessage', {
            'chat_id': recipient.chat_id,
            'text': "Проверка связи: программа учёта шиномонтажа подключена.",
        }))
        name = info.get('username') or info.get('first_name') or 'бот'
        return name, result

    # ------------------------------------------------------------------
    # Отправка не блокируя интерфейс
    # ------------------------------------------------------------------

    def send_async(self, func, on_done=None):
        """
        Выполнить отправку в отдельном потоке.

        func — вызов вроде lambda: service.send_document(path).
        on_done получает (успех, сообщение) и вызывается из того же потока,
        поэтому в интерфейсе результат нужно показывать через after().
        """
        def worker():
            try:
                result = func()
                if on_done:
                    # Отправка нескольким получателям сама расскажет,
                    # кому дошло, а кому нет
                    message = (result.summary() if isinstance(result, DeliveryResult)
                               else "Отправлено в Telegram")
                    on_done(True, message)
            except TelegramError as e:
                if on_done:
                    on_done(False, str(e))
            except Exception as e:
                if on_done:
                    on_done(False, f"Не удалось отправить: {e}")

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread


def _name_of(chat):
    """Как показать человека в списке: имя, фамилия, иначе @логин."""
    parts = [chat.get('first_name'), chat.get('last_name')]
    name = ' '.join(part for part in parts if part).strip()

    if name:
        return name
    if chat.get('username'):
        return '@' + chat['username']
    if chat.get('title'):
        return chat['title']        # групповой чат
    return ''


def _encode_multipart(fields, files):
    """Собрать тело запроса с файлом вручную — без сторонних библиотек."""
    boundary = uuid.uuid4().hex
    parts = []

    for name, value in fields.items():
        parts.append(f'--{boundary}\r\n'.encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(f'{value}\r\n'.encode())

    for name, (filename, content) in files.items():
        mime = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        parts.append(f'--{boundary}\r\n'.encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode())
        parts.append(f'Content-Type: {mime}\r\n\r\n'.encode())
        parts.append(content)
        parts.append(b'\r\n')

    parts.append(f'--{boundary}--\r\n'.encode())
    return b''.join(parts), f'multipart/form-data; boundary={boundary}'
