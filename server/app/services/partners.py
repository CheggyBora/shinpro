"""
Работы у партнёров на сервере (решения владельца 13.11.2026).

Работу заводит программа в цеху (задача с полями партнёра, приходит
обменом задач). Здесь — то, что делают с ней вне цеха:

  · переписка с партнёром через бота организации: заявка с кнопками
    «Назначить цену» / «Не возьмусь», потом «Готово, можно забирать»;
    видят те, кто согласует (кабинет на телефоне), и главный (дашборд);
  · цена партнёра — из его ответа или руками; согласование цены с
    клиентом — ссылкой (покраска, шины);
  · «партнёр сделал», отказ, оплата партнёру из дашборда.

Каждая правка ставит задаче свежее время: цех при обмене берёт её и
делает своё — досчитывает зарплату, проводит РКО, убирает строку.
"""
import os
import re
import secrets

from app.config import settings
from app.models import Account, Counterparty, PartnerMessage, PartnerQuote, Shop, Task
from app.utils import now as shop_now

ST_AGREE, ST_CLIENT, ST_WORK, ST_WAIT, ST_PAID, ST_REFUSED = (
    'agree', 'client', 'work', 'wait_pay', 'paid', 'refused')
STATUS_TITLES = {
    ST_AGREE: 'Согласование с партнёром', ST_CLIENT: 'Согласование с клиентом',
    ST_WORK: 'В работе у партнёра', ST_WAIT: 'Закрыто — ждёт оплаты',
    ST_PAID: 'Оплачено', ST_REFUSED: 'Отказ',
}
KIND_TITLES = {'work': 'Работа', 'paint': 'Покраска', 'tires': 'Заказ шин'}
PAY_TITLES = {'cash': 'Наличные из кассы (РКО)', 'noncash': 'Безнал с расчётного счёта',
              'other': 'Другое'}
OPEN = (ST_AGREE, ST_CLIENT, ST_WORK, ST_WAIT)


class PartnerError(ValueError):
    pass


def money(value):
    return f'{value:,.0f} ₽'.replace(',', ' ') if value is not None else '—'


def _price(value):
    if value in (None, ''):
        return None
    text = re.sub(r'[^\d,.]', '', str(value)).replace(',', '.')
    try:
        number = round(float(text), 2)
    except ValueError:
        raise PartnerError('Цена — числом, например 2000')
    if number < 0:
        raise PartnerError('Цена не может быть меньше нуля')
    return number


# ----------------------------------------------------------------------
# Работы
# ----------------------------------------------------------------------

def query(db, shop_ids):
    return db.query(Task).filter(Task.shop_id.in_(list(shop_ids)),
                                 Task.partner_kind.isnot(None), Task.deleted.is_(False))


def job(db, shop_ids, uid):
    return query(db, shop_ids).filter(Task.uid == uid).first()


def party_of(db, task):
    if not task.counterparty_uid:
        return None
    return db.query(Counterparty).filter(Counterparty.shop_id == task.shop_id,
                                         Counterparty.uid == task.counterparty_uid).first()


def needs_client(task):
    if task.needs_client is not None:
        return bool(task.needs_client)
    return task.partner_kind in ('paint', 'tires')


def job_dict(db, task, messages=False):
    party = party_of(db, task)
    margin = None if task.partner_price is None else round((task.our_price or 0) - task.partner_price, 2)
    result = {
        'uid': task.uid, 'id': task.id, 'shop_id': task.shop_id, 'title': task.title,
        'note': task.note, 'kind': task.partner_kind,
        'kind_title': KIND_TITLES.get(task.partner_kind, ''),
        'status': task.partner_status, 'status_title': STATUS_TITLES.get(task.partner_status, ''),
        'license_plate': task.license_plate, 'client_name': task.client_name,
        'our_price': task.our_price, 'partner_price': task.partner_price, 'margin': margin,
        'needs_client': needs_client(task), 'order_local_id': task.order_local_id,
        'partner': party.name if party else '', 'partner_bot': bool(party and party.telegram_chat_id),
        'pay_method': task.pay_method, 'pay_title': PAY_TITLES.get(task.pay_method, ''),
        'pay_note': task.pay_note, 'due_date': task.due_date.isoformat() if task.due_date else None,
    }
    if messages:
        result['messages'] = [message_dict(m) for m in messages_of(db, task)]
        quote = db.query(PartnerQuote).filter(PartnerQuote.task_uid == task.uid,
                                              PartnerQuote.shop_id == task.shop_id).order_by(
            PartnerQuote.id.desc()).first()
        result['quote'] = {'state': quote.state, 'price': quote.price} if quote else None
    return result


def jobs(db, shop_ids, open_only=False):
    rows = query(db, shop_ids)
    if open_only:
        rows = rows.filter(Task.partner_status.in_(OPEN))
    return rows.order_by(Task.updated_at.desc()).all()


def summary(db, shop_ids):
    """Оплата партнёрам, в работе, маржа по оплаченным работам."""
    rows = jobs(db, shop_ids)
    owe = sum(t.partner_price or 0 for t in rows if t.partner_status == ST_WAIT)
    return {
        'owe': round(owe, 2),
        'waiting': sum(1 for t in rows if t.partner_status == ST_WAIT),
        'in_work': sum(1 for t in rows if t.partner_status in (ST_AGREE, ST_CLIENT, ST_WORK)),
        'no_price': sum(1 for t in rows if t.partner_price is None
                        and t.partner_status not in (ST_REFUSED,)),
        'margin': round(sum((t.our_price or 0) - t.partner_price for t in rows
                            if t.partner_price is not None and t.partner_status != ST_REFUSED), 2),
    }


def _touch(task):
    task.updated_at = shop_now()


def set_partner_price(db, task, price, who, from_partner=False):
    if task.partner_status == ST_PAID:
        raise PartnerError('Партнёру уже заплатили — цену не меняем')
    task.partner_price = _price(price)
    if task.partner_status == ST_AGREE and task.partner_price is not None:
        task.partner_status = ST_CLIENT if needs_client(task) else ST_WORK
    _touch(task)
    add_message(db, task, 'system', who,
                (f'Партнёр назначил цену: {money(task.partner_price)}' if from_partner
                 else f'Цена партнёра: {money(task.partner_price)} (вписал {who})'))
    db.commit()
    return task


def finish(db, task, who):
    if task.partner_status not in (ST_AGREE, ST_CLIENT, ST_WORK):
        raise PartnerError(f'Работа уже: {STATUS_TITLES.get(task.partner_status, "")}')
    task.partner_status = ST_WAIT
    task.done_by = who
    _touch(task)
    add_message(db, task, 'system', who, f'Готово — ждёт оплаты партнёру ({who})')
    db.commit()
    return task


def client_answer(db, task, yes, who):
    if task.partner_status not in (ST_CLIENT, ST_AGREE):
        raise PartnerError('Клиента уже спросили')
    task.partner_status = ST_WORK if yes else ST_REFUSED
    if not yes:
        task.done_at = shop_now()
    _touch(task)
    add_message(db, task, 'system', who, 'Клиент согласен — в работу' if yes else 'Клиент отказался')
    db.commit()
    return task


def refuse(db, task, who, why='партнёр не взялся'):
    if task.partner_status in (ST_PAID, ST_REFUSED):
        raise PartnerError('Работа уже закрыта')
    task.partner_status = ST_REFUSED
    task.done_at = shop_now()
    _touch(task)
    add_message(db, task, 'system', who, f'Отказ: {why}')
    db.commit()
    return task


def pay(db, tasks, method, note, who):
    """Оплатили партнёру из дашборда. РКО или расход по безналу проведёт цех."""
    if method not in PAY_TITLES:
        raise PartnerError('Выберите, чем платим')
    for task in tasks:
        if task.partner_status == ST_PAID:
            raise PartnerError(f'«{task.title}» уже оплачена')
        if task.partner_status == ST_REFUSED:
            raise PartnerError(f'«{task.title}» — отказ, платить нечего')
        if task.partner_price is None:
            raise PartnerError(f'У «{task.title}» не указана цена партнёра')
    moment = shop_now()
    for task in tasks:
        task.partner_status = ST_PAID
        task.pay_method = method
        task.pay_note = (note or '')[:300] or None
        task.paid_at = moment
        task.done_at = task.done_at or moment
        _touch(task)
        add_message(db, task, 'system', who,
                    f'Оплачено партнёру: {PAY_TITLES[method].lower()}, {money(task.partner_price)}')
    db.commit()
    return tasks


# ----------------------------------------------------------------------
# Переписка
# ----------------------------------------------------------------------

def messages_of(db, task):
    return db.query(PartnerMessage).filter(PartnerMessage.shop_id == task.shop_id,
                                           PartnerMessage.task_uid == task.uid).order_by(
        PartnerMessage.id).all()


def message_dict(row):
    return {'id': row.id, 'author': row.author, 'name': row.name or '', 'text': row.text or '',
            'photo': bool(row.photo), 'at': row.created_at.isoformat() if row.created_at else None}


def add_message(db, task, author, name, text=None, photo=None, telegram_message_id=None):
    row = PartnerMessage(shop_id=task.shop_id, task_uid=task.uid, author=author,
                         name=(name or '')[:100] or None, text=text, photo=photo,
                         telegram_message_id=telegram_message_id)
    db.add(row)
    db.flush()
    return row


def save_photo(task, data, content_type='image/jpeg'):
    """Фото к переписке — в папку фото точки. Возвращает путь от неё."""
    if len(data) > settings.PHOTO_MAX_BYTES:
        raise PartnerError('Фото слишком большое')
    ext = '.png' if 'png' in (content_type or '') else '.jpg'
    folder = os.path.join(settings.PHOTO_DIR, str(task.shop_id), 'partners')
    os.makedirs(folder, exist_ok=True)
    name = f'{task.uid[:8]}-{secrets.token_hex(6)}{ext}'
    with open(os.path.join(folder, name), 'wb') as out:
        out.write(data)
    return f'{task.shop_id}/partners/{name}'


def photo_path(row):
    return os.path.join(settings.PHOTO_DIR, row.photo.replace('/', os.sep)) if row.photo else None


def _account_of(db, task):
    shop = db.get(Shop, task.shop_id)
    return db.get(Account, shop.account_id) if shop is not None and shop.account_id else None


def partner_chat(db, task):
    """Чат партнёра с ботом: привязан — он; нет — ищем по нику среди написавших боту."""
    from app.models import TelegramChat
    party = party_of(db, task)
    if party is None:
        return None, None
    if party.telegram_chat_id:
        return party, party.telegram_chat_id
    account = _account_of(db, task)
    if account is not None and party.telegram:
        row = db.query(TelegramChat).filter(TelegramChat.account_id == account.id,
                                            TelegramChat.username == party.telegram.lower()).first()
        if row is not None:
            party.telegram_chat_id = row.chat_id
            db.flush()
            return party, row.chat_id
    return party, None


def invite_link(db, task_or_party):
    """Ссылка-приглашение партнёру к боту: по ней он привяжется сам."""
    party = task_or_party if isinstance(task_or_party, Counterparty) else party_of(db, task_or_party)
    shop = db.get(Shop, party.shop_id) if party is not None else None
    account = db.get(Account, shop.account_id) if shop is not None and shop.account_id else None
    if account is None or not account.telegram_bot_username:
        return None
    return f'https://t.me/{account.telegram_bot_username}?start=p-{party.uid[:12]}'


def _buttons(task):
    if task.partner_status == ST_AGREE:
        return [[{'text': 'Назначить цену', 'callback_data': f'pp:{task.id}'},
                 {'text': 'Не возьмусь', 'callback_data': f'pn:{task.id}'}]]
    if task.partner_status in (ST_WORK, ST_CLIENT):
        return [[{'text': 'Готово, можно забирать', 'callback_data': f'pd:{task.id}'}]]
    return None


def _send(account, chat_id, text, buttons=None):
    from app.services import telegram
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML',
               'disable_web_page_preview': True}
    if buttons:
        payload['reply_markup'] = {'inline_keyboard': buttons}
    answer = telegram.call(account.telegram_bot_token, 'sendMessage', payload) or {}
    return answer.get('message_id') if isinstance(answer, dict) else None


def _escape(text):
    return (text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def send_job(db, task, who):
    """Заявка партнёру: что сделать, машина, фото из переписки, кнопки."""
    account = _account_of(db, task)
    if account is None or not account.telegram_bot_token:
        raise PartnerError('Бот не подключён: дашборд → «Оформление» → «Бот в Telegram»')
    party, chat = partner_chat(db, task)
    if party is None:
        raise PartnerError('У работы нет партнёра')
    if chat is None:
        link = invite_link(db, task)
        raise PartnerError(f'«{party.name}» ещё не подключён к боту. Отправьте ему ссылку: {link}'
                           if link else f'«{party.name}» ещё не подключён к боту')
    from app.services import telegram
    for row in messages_of(db, task):
        if row.photo and row.author == 'staff':
            try:
                with open(photo_path(row), 'rb') as source:
                    telegram.send_photo(account, chat, source.read())
            except Exception:
                pass
    shop = db.get(Shop, task.shop_id)
    text = (f'<b>Заявка: {_escape(task.title)}</b>'
            + (f'\n{_escape(task.note)}' if task.note else '')
            + (f'\nМашина {_escape(task.license_plate)}' if task.license_plate else '')
            + f'\nОт: {_escape(shop.name if shop else "")}'
            + ('\n\nКогда сможете и сколько?' if task.partner_status == ST_AGREE else ''))
    message_id = _send(account, chat, text, _buttons(task))
    add_message(db, task, 'staff', who, 'Заявка отправлена партнёру', telegram_message_id=message_id)
    db.commit()
    return task


def staff_message(db, task, who, text=None, photo=None):
    """Сотрудник пишет в переписку; партнёр подключён к боту — ему же."""
    text = (text or '').strip()
    if not text and not photo:
        raise PartnerError('Напишите сообщение или приложите фото')
    row = add_message(db, task, 'staff', who, text or None, photo=photo)
    account = _account_of(db, task)
    party, chat = partner_chat(db, task)
    if account is not None and account.telegram_bot_token and chat:
        from app.services import telegram
        try:
            if photo:
                with open(photo_path(row), 'rb') as source:
                    telegram.send_photo(account, chat, source.read(),
                                        caption=f'{task.title}: {text}' if text else task.title)
            else:
                row.telegram_message_id = _send(account, chat,
                                                f'<b>{_escape(task.title)}</b>\n{_escape(text)}')
        except Exception:
            pass
    db.commit()
    return row


# ----------------------------------------------------------------------
# Партнёр отвечает в боте
# ----------------------------------------------------------------------

def _shops_of(db, account):
    return [s.id for s in db.query(Shop).filter(Shop.account_id == account.id).all()]


def _party_by_chat(db, account, chat_id):
    return db.query(Counterparty).filter(Counterparty.shop_id.in_(_shops_of(db, account)),
                                         Counterparty.telegram_chat_id == str(chat_id),
                                         Counterparty.deleted.is_(False)).first()


def _task_by_id(db, account, task_id):
    try:
        task_id = int(task_id)
    except (TypeError, ValueError):
        return None
    return db.query(Task).filter(Task.id == task_id, Task.shop_id.in_(_shops_of(db, account)),
                                 Task.partner_kind.isnot(None)).first()


def handle_update(db, account, update):
    """
    Сообщение или кнопка от партнёра. True — разобрали здесь; False —
    это не партнёр, пусть разбирает обычный бот (клиенты, сотрудники).
    """
    from app.models import TelegramChat
    from app.services import telegram

    callback = (update or {}).get('callback_query')
    if callback:
        chat_id = str(((callback.get('message') or {}).get('chat') or {}).get('id') or '')
        data = callback.get('data') or ''
        try:
            telegram.call(account.telegram_bot_token, 'answerCallbackQuery',
                          {'callback_query_id': callback.get('id')})
        except Exception:
            pass
        kind, _, task_id = data.partition(':')
        task = _task_by_id(db, account, task_id)
        party = _party_by_chat(db, account, chat_id)
        if task is None or party is None or party.uid != task.counterparty_uid:
            return True
        try:
            if kind == 'pp':
                chat = db.query(TelegramChat).filter(TelegramChat.account_id == account.id,
                                                     TelegramChat.chat_id == chat_id).first()
                if chat is not None:
                    chat.pending = f'price:{task.id}'
                db.commit()
                _send(account, chat_id, f'Напишите цену за «{_escape(task.title)}» числом, например 2000')
            elif kind == 'pn':
                refuse(db, task, party.name, 'партнёр не возьмётся')
                _send(account, chat_id, 'Записали: не возьмётесь. Спасибо!')
            elif kind == 'pd':
                finish(db, task, party.name)
                _send(account, chat_id, f'Спасибо! Отметили: «{_escape(task.title)}» готово.')
        except PartnerError as e:
            db.rollback()
            _send(account, chat_id, str(e))
        return True

    message = (update or {}).get('message') or {}
    chat_id = str((message.get('chat') or {}).get('id') or '')
    text = (message.get('text') or message.get('caption') or '').strip()
    if not chat_id:
        return False

    if text.startswith('/start p-'):
        code = text.split('p-', 1)[1].strip()
        party = db.query(Counterparty).filter(Counterparty.shop_id.in_(_shops_of(db, account)),
                                              Counterparty.uid.startswith(code)).first() if code else None
        if party is None:
            _send(account, chat_id, 'Ссылка устарела — попросите новую у шиномонтажа.')
            return True
        party.telegram_chat_id = chat_id
        db.commit()
        _send(account, chat_id, f'Готово, «{_escape(party.name)}» подключён. Заявки шиномонтажа '
                                f'будут приходить сюда — с кнопками «Назначить цену» и «Готово».')
        return True

    party = _party_by_chat(db, account, chat_id)
    if party is None:
        return False

    chat = db.query(TelegramChat).filter(TelegramChat.account_id == account.id,
                                         TelegramChat.chat_id == chat_id).first()
    if chat is not None and (chat.pending or '').startswith('price:') and text:
        task = _task_by_id(db, account, chat.pending.split(':', 1)[1])
        try:
            price = _price(text)
        except PartnerError:
            price = None
        if task is not None and price:
            chat.pending = None
            set_partner_price(db, task, price, party.name, from_partner=True)
            _send(account, chat_id, f'Цена {money(price)} отправлена. Ждём подтверждения.')
            return True

    # Обычное сообщение — в переписку работы: ответ на заявку — к ней,
    # иначе — к последней открытой работе этого партнёра
    task = None
    reply = (message.get('reply_to_message') or {}).get('message_id')
    if reply:
        linked = db.query(PartnerMessage).filter(PartnerMessage.telegram_message_id == reply).first()
        if linked is not None:
            task = db.query(Task).filter(Task.shop_id == linked.shop_id,
                                         Task.uid == linked.task_uid).first()
    if task is None:
        task = db.query(Task).filter(Task.shop_id == party.shop_id,
                                     Task.counterparty_uid == party.uid,
                                     Task.partner_kind.isnot(None),
                                     Task.partner_status.in_(OPEN)).order_by(
            Task.updated_at.desc()).first()
    if task is None:
        _send(account, chat_id, 'Открытых заявок нет — по вопросам лучше позвонить в шиномонтаж.')
        return True
    photo = None
    sizes = message.get('photo') or []
    if sizes:
        try:
            info = telegram.call(account.telegram_bot_token, 'getFile', {'file_id': sizes[-1]['file_id']})
            import urllib.request
            url = f'https://api.telegram.org/file/bot{account.telegram_bot_token}/{info["file_path"]}'
            with urllib.request.urlopen(url, timeout=30) as answer:
                photo = save_photo(task, answer.read())
        except Exception:
            photo = None
    add_message(db, task, 'partner', party.name, text or None, photo=photo,
                telegram_message_id=message.get('message_id'))
    db.commit()
    return True


# ----------------------------------------------------------------------
# Цена клиенту на согласование
# ----------------------------------------------------------------------

def make_quote(db, task, who):
    """Ссылка клиенту: цена работы, «Да» / «Нет» / «Позвоните»."""
    if task.partner_status not in (ST_CLIENT, ST_AGREE):
        raise PartnerError('Согласовывать с клиентом нечего')
    if not task.our_price:
        raise PartnerError('Нет цены клиенту')
    quote = PartnerQuote(shop_id=task.shop_id, task_uid=task.uid, token=secrets.token_urlsafe(16),
                         price=task.our_price, state='pending', created_at=shop_now())
    db.add(quote)
    add_message(db, task, 'system', who, f'Цена отправлена клиенту: {money(task.our_price)}')
    db.commit()
    return quote


def quote_of(db, token):
    return db.query(PartnerQuote).filter(PartnerQuote.token == token).first() if token else None


def answer_quote(db, quote, answer):
    if quote.state != 'pending':
        return quote
    if answer not in ('yes', 'no', 'call'):
        raise PartnerError('Не понял ответ')
    quote.state = answer
    quote.answered_at = shop_now()
    task = db.query(Task).filter(Task.shop_id == quote.shop_id, Task.uid == quote.task_uid).first()
    if task is not None:
        if answer == 'call':
            add_message(db, task, 'system', 'Клиент', 'Клиент просит позвонить')
            _touch(task)
            db.commit()
        else:
            client_answer(db, task, answer == 'yes', 'Клиент')
    db.commit()
    return quote


def send_quote(db, task, quote, base_url):
    """Клиенту в Telegram, если он подключён к боту; иначе — ссылку отдаём сотруднику."""
    from app.models import Client
    from app.services import telegram
    link = f'{base_url.rstrip("/")}/pq/{quote.token}'
    account = _account_of(db, task)
    phone = re.sub(r'\D', '', task.client_phone or '')
    client = None
    if account is not None and phone:
        for row in db.query(Client).filter(Client.account_id == account.id,
                                           Client.telegram_chat_id.isnot(None)).all():
            if re.sub(r'\D', '', row.phone or '')[-10:] == phone[-10:]:
                client = row
                break
    sent = False
    if client is not None and account.telegram_bot_token:
        try:
            telegram.send_message(account, client.telegram_chat_id,
                                  f'<b>{_escape(task.title)}</b>\nЦена: {money(task.our_price)}. Делаем?',
                                  buttons=[('Ответить', link)])
            sent = True
        except Exception:
            sent = False
    return {'link': link, 'sent': sent}
