"""
Обмен с сервером приложения.

Наверх уходит копия того, что клиент видит в приложении: клиенты,
машины, история визитов, шины на хранении и загрузка цеха. Вниз
спускаются заявки «привезите мой комплект к дате» и выплаты зарплаты,
которые владелец отметил переводом на карту.

Записи здесь нет намеренно: она живёт на сервере в одном экземпляре,
и программа обращается к ней напрямую — см. services/booking_api.py.

Наряды, оплата, зарплата, смены, прайс, печать — интернета не касаются
вообще и продолжают работать, даже когда связи нет неделю.

Пропала связь — обмен просто не удался, ошибка ушла в журнал, программа
работает дальше. Связь вернулась — накопленное уходит наверх. Заявка
висит на сервере, пока цех её не подтвердит: лучше повторить дважды,
чем потерять один раз.
"""
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from logger import log
from utils import get_moscow_time, as_naive

URL_KEY = 'sync_server_url'
KEY_KEY = 'sync_server_key'
ENABLED_KEY = 'sync_enabled'
LAST_OK_KEY = 'sync_last_success'

# Сколько ждать ответа. Больше — и обмен подвиснет вместе с интерфейсом,
# если сервер отвечает медленно
TIMEOUT_SECONDS = 20

# Как часто выходить на связь. Раз в десять минут: здесь ездят копии —
# клиенты, машины, визиты, хранение, — и отстать на десять минут им
# нечем повредить. Записи этим обменом не идут: за ними программа
# ходит на сервер в тот же миг, когда приёмщик сохраняет, иначе цех
# и приложение разошлись бы в том, какое время свободно
INTERVAL_MINUTES = 10

# Насколько назад отдавать историю визитов при первом обмене
HISTORY_DAYS = 730


class SyncError(Exception):
    pass


class SyncService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Настройки
    # ------------------------------------------------------------------

    def _settings(self):
        from services.settings_service import SettingsService
        return SettingsService(self.db)

    def get_url(self):
        return (self._settings().get(URL_KEY, '') or '').strip().rstrip('/')

    def get_key(self):
        return (self._settings().get(KEY_KEY, '') or '').strip()

    def is_enabled(self):
        settings = self._settings()
        return (settings.get(ENABLED_KEY, '0') == '1'
                and bool(self.get_url()) and bool(self.get_key()))

    def save_settings(self, url, key, enabled):
        settings = self._settings()
        settings.set(URL_KEY, (url or '').strip().rstrip('/'), commit=False)
        settings.set(KEY_KEY, (key or '').strip(), commit=False)
        settings.set(ENABLED_KEY, '1' if enabled else '0')

    def last_success(self):
        raw = self._settings().get(LAST_OK_KEY, '') or ''
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Запросы
    # ------------------------------------------------------------------

    def _call(self, method, path, payload=None):
        url = self.get_url()
        if not url:
            raise SyncError('Не задан адрес сервера')

        request = urllib.request.Request(
            f'{url}{path}',
            data=json.dumps(payload, ensure_ascii=False, default=_encode).encode('utf-8')
            if payload is not None else None,
            headers={
                'Content-Type': 'application/json',
                'X-Sync-Key': self.get_key(),
            },
            method=method)

        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            detail = ''
            try:
                detail = json.loads(e.read().decode('utf-8')).get('detail', '')
            except Exception:
                pass
            raise SyncError(f'Сервер отклонил запрос: {detail or e}')
        except urllib.error.URLError as e:
            raise SyncError(f'Нет связи с сервером: {e.reason}')
        except Exception as e:
            raise SyncError(f'Ошибка обмена: {e}')

    def test_connection(self):
        """Проверить адрес и ключ. Возвращает сводку с сервера."""
        return self._call('GET', '/sync/state')

    # ------------------------------------------------------------------
    # Наверх
    # ------------------------------------------------------------------

    def collect_push(self, changed_since=None):
        """
        Собрать то, что уходит наверх.

        changed_since — отметка сервера: наряды до неё у него уже есть.
        Без неё отдаём всю историю: сервер либо новый, либо его подняли
        заново из пустой базы.
        """
        from models import Client, Car, Employee, Shift

        clients = [{'local_id': row.id, 'phone': row.phone, 'name': row.name}
                   for row in self.db.query(Client).all()]

        cars = [{'local_id': row.id,
                 'license_plate': row.license_plate,
                 'client_local_id': row.client_id,
                 'vehicle_type': row.vehicle_type,
                 'wheel_diameter': row.wheel_diameter,
                 'wheels_assembled': row.wheels_assembled}
                for row in self.db.query(Car).all()]

        employees = [{'local_id': row.id,
                      'name': row.name,
                      'salary_percent': row.salary_percent,
                      'is_active': bool(row.is_active)}
                     for row in self.db.query(Employee).all()]

        shifts = [{'local_id': row.id,
                   'started_at': as_naive(row.start_time),
                   'ended_at': as_naive(row.end_time),
                   'status': row.status,
                   'open_posts': row.open_posts,
                   'total_salary': row.total_salary or 0.0}
                  for row in self._recent_shifts(changed_since)]

        return {
            'clients': clients,
            'cars': cars,
            'visits': self._collect_visits(changed_since),
            'employees': employees,
            'shifts': shifts,
            'payouts': self._collect_payouts(changed_since),
            'storage': self._collect_storage(),
            'queue': self._collect_queue(),
            'settings': self._collect_settings(),
        }

    def _collect_payouts(self, changed_since):
        """
        Выданная зарплата.

        Отдаём и те выплаты, что пришли из дашборда: сервер по local_id
        поймёт, что его же запись доехала до цеха и учтена.
        """
        from models import SalaryPayout

        query = self.db.query(SalaryPayout)
        if changed_since is not None:
            query = query.filter(SalaryPayout.paid_at >= changed_since)

        return [{'local_id': row.id,
                 'employee_local_id': row.employee_id,
                 'amount': row.amount or 0.0,
                 'method': row.method,
                 'paid_at': as_naive(row.paid_at),
                 'comment': row.comment,
                 'is_advance': bool(row.is_advance),
                 'source': row.source}
                for row in query.all()]

    def _recent_shifts(self, changed_since):
        """Смены, которые могли измениться: открытые и свежезакрытые."""
        from models import Shift

        query = self.db.query(Shift)
        if changed_since is not None:
            # Открытую смену шлём всегда: её итог растёт с каждой оплатой
            query = query.filter(
                (Shift.status == 'open') |
                (Shift.start_time >= changed_since - timedelta(days=2)))
        return query.all()

    def _collect_visits(self, changed_since=None):
        """
        Оплаченные наряды: для кабинета клиента и для дашборда владельца.

        Клиенту из этого покажут дату, услуги и рекомендации. Владельцу —
        ещё и деньги, расходники и начисления. Наряд один, поэтому и
        строка одна: две — «для клиента» и «для владельца» — разошлись бы
        после первого возврата.

        Уходят только наряды, изменившиеся после changed_since. Менять
        оплаченный наряд можно ровно тремя способами — возврат, сторно,
        удаление, — и каждый оставляет свою отметку времени.
        """
        from models import WorkOrder, SalaryTransaction
        from services.order_service import OrderService

        since = get_moscow_time() - timedelta(days=HISTORY_DAYS)
        query = self.db.query(WorkOrder).filter(
            WorkOrder.status == 'paid',
            WorkOrder.paid_at.isnot(None),
            WorkOrder.paid_at >= since)

        orders = query.all()

        service = OrderService(self.db)
        visits = []
        for order in orders:
            changed_at = _changed_at(order)

            if changed_since is not None and changed_at is not None \
                    and changed_at < changed_since:
                continue

            try:
                items = service.get_order_items(order.id)
                services = '\n'.join(
                    f"{item.service.name}"
                    + (f" x{item.quantity}" if item.quantity > 1 else '')
                    for item in items if item.service)
                lines = [{
                    'local_id': item.id,
                    'service_name': item.service.name if item.service else '—',
                    'quantity': item.quantity or 1,
                    'unit_price': service.item_unit_price(item),
                    'discount_percent': item.discount_percent or 0,
                    'total': service.item_total(item),
                    'consumable_cost': service.item_consumables(item),
                    'comment': item.comment,
                } for item in items]
            except Exception as e:
                log.warning(f"Наряд №{order.id} не попал в обмен: {e}")
                continue

            accruals = [{
                'employee_local_id': row.employee_id,
                'amount': row.amount or 0.0,
                'accrued_at': as_naive(row.transaction_date),
            } for row in self.db.query(SalaryTransaction).filter(
                SalaryTransaction.work_order_id == order.id).all()]

            visits.append({
                'local_id': order.id,
                'client_local_id': order.client_id,
                'license_plate': order.car.license_plate if order.car else None,
                'visited_at': as_naive(order.paid_at),
                'total_amount': order.total_amount or 0.0,
                'services': services or None,
                'recommendations': order.recommendations,
                'is_warranty': bool(getattr(order, 'is_warranty', False)),

                'changed_at': as_naive(changed_at),
                'shift_local_id': order.shift_id,
                'vehicle_type': order.vehicle_type,
                'wheel_diameter': order.wheel_diameter,
                'payment_method': order.payment_method,
                'consumables_amount': order.consumables_amount or 0.0,
                'salary_base': order.salary_base or 0.0,
                'general_discount': order.general_discount or 0,
                'rim_discount': order.rim_discount or 0,
                'auto_discount': bool(order.auto_discount),
                'refunded_amount': order.refunded_amount or 0.0,
                'refunded_at': as_naive(order.refunded_at),
                'refund_type': order.refund_type,
                'refund_reason': order.refund_reason,
                'is_deleted': bool(order.is_deleted),
                'planned_minutes': order.planned_minutes or 0,
                'started_at': as_naive(order.started_at),
                'finished_at': as_naive(order.finished_at),

                'items': lines,
                'accruals': accruals,
            })
        return visits

    def _collect_storage(self):
        from models import TireStorage, Car

        rows = self.db.query(TireStorage).filter(
            TireStorage.status == 'stored').all()

        storage = []
        for row in rows:
            # У хранения свой номер машины строкой — владельца ищем по нему
            car = self.db.query(Car).filter(
                Car.license_plate == row.car_number).first()
            storage.append({
                'local_id': row.id,
                'client_local_id': car.client_id if car else None,
                'license_plate': row.car_number,
                'storage_type': row.storage_type,
                'wheel_type': row.wheel_type,
                'diameter': row.diameter,
                'brand': row.brand,
                'accepted_at': as_naive(row.accepted_date),
                'expires_at': as_naive(row.expires_at),
                'status': row.status,
            })
        return storage

    def _collect_booking_days(self, today):
        from services.appointment_service import AppointmentService

        service = AppointmentService(self.db)
        days = []
        for offset in range(DAYS_AHEAD):
            day = today + timedelta(days=offset)
            days.append({
                'day': day.isoformat(),
                'posts': service.get_posts_for_day(day),
                'opens_at': '09:00',
                'closes_at': '21:00',
                'is_closed': False,
            })
        return days

    def _collect_queue(self):
        """
        Что сейчас в цеху.

        Считаем по нарядам: начатые и незакрытые — в работе, сохранённые
        но не начатые — ждут. Прогноз освобождения даём только когда
        есть за что зацепиться, иначе лучше промолчать.
        """
        from models import WorkOrder
        from services.shift_service import ShiftService

        shift = ShiftService(self.db).get_current_shift()
        if shift is None:
            return {'cars_in_work': 0, 'cars_waiting': 0, 'open_posts': 0,
                    'free_in_minutes': None, 'shift_is_open': False}

        in_work = self.db.query(WorkOrder).filter(
            WorkOrder.status != 'paid',
            WorkOrder.started_at.isnot(None),
            WorkOrder.finished_at.is_(None)).all()

        waiting = self.db.query(WorkOrder).filter(
            WorkOrder.status != 'paid',
            WorkOrder.started_at.is_(None)).count()

        posts = shift.open_posts or 1
        free_in = None
        if len(in_work) >= posts and in_work:
            # Ближайший освободится, когда закончится самый ранний наряд
            now = get_moscow_time()
            remaining = []
            for order in in_work:
                planned = order.planned_minutes or 0
                started = as_naive(order.started_at)
                spent = (now - started).total_seconds() / 60 if started else 0
                remaining.append(max(0, planned - spent))
            free_in = int(min(remaining)) if remaining else None
        elif len(in_work) < posts:
            free_in = 0

        return {
            'cars_in_work': len(in_work),
            'cars_waiting': waiting,
            'open_posts': posts,
            'free_in_minutes': free_in,
            'shift_is_open': True,
        }

    def _collect_settings(self):
        """Настройки, по которым приложение должно считать так же, как цех."""
        from services.settings_service import SettingsService
        from services.company_service import get_company

        settings = SettingsService(self.db)
        company = get_company(self.db)

        from services.telegram_service import TelegramService

        telegram = TelegramService(self.db)
        chats = ','.join(r.chat_id for r in telegram.get_active_recipients())

        return {
            'booking_minutes_assembled': settings.get('booking_minutes_assembled'),
            'booking_minutes_tires': settings.get('booking_minutes_tires'),
            'booking_minutes_unknown': settings.get('booking_minutes_unknown'),
            'booking_slot_step': settings.get('booking_slot_step'),
            'booking_opens_at': settings.get('booking_opens_at'),
            'booking_closes_at': settings.get('booking_closes_at'),

            # По этим числам сервер сам предупреждает владельцев: что
            # заканчивается хранение и что пора переобуваться. Считать
            # их должен цех — сроки и сезон у каждого свои
            'storage_warn_days': settings.get('storage_warn_days'),
            'season_autumn_at': settings.get('season_autumn_at'),
            'season_spring_at': settings.get('season_spring_at'),
            'season_reminders_enabled': settings.get('season_reminders_enabled'),

            'shop_name': company.name,
            'shop_phone': company.phone,
            'shop_address': company.address,

            # Бот и получатели — те же, что для сводки по смене. Иначе
            # настраивать Telegram пришлось бы дважды, в программе и на
            # сервере, и они бы разъехались
            'telegram_token': telegram.get_token(),
            'telegram_chats': chats,
        }

    # ------------------------------------------------------------------
    # Вниз
    # ------------------------------------------------------------------

    def apply_payouts(self, payouts):
        """
        Принять выплаты, отмеченные владельцем в дашборде.

        Возвращает подтверждения. Пока цех не подтвердил, выплата
        остаётся на сервере и придёт снова: потерянная выплата — это
        деньги, которые человек получил, а программа об этом не знает.
        """
        from services.payout_service import PayoutService, PayoutError
        from models import SalaryPayout

        service = PayoutService(self.db)
        acks = {'payouts': []}

        for item in payouts:
            server_id = item.get('server_id')
            try:
                # Та же выплата могла прийти дважды — второй раз деньги
                # не выдаём, просто подтверждаем снова
                already = self.db.query(SalaryPayout).filter(
                    SalaryPayout.server_id == server_id).first()

                if already is None:
                    already = service.pay(
                        item['employee_local_id'], item['amount'],
                        item.get('method', 'card'),
                        comment=item.get('comment'),
                        allow_advance=True,
                        source='dashboard',
                        server_id=server_id)

                acks['payouts'].append({'server_id': server_id,
                                        'local_id': already.id,
                                        'accepted': True})
            except (PayoutError, KeyError, TypeError) as e:
                self.db.rollback()
                log.error(f"Выплата с сервера не принята: {e}")
                acks['payouts'].append({'server_id': server_id,
                                        'accepted': False,
                                        'reason': str(e)[:200]})

        return acks

    def apply_pull(self, requests):
        """
        Принять заявки на комплекты. Возвращает подтверждения для сервера.

        Заявка остаётся на сервере, пока цех её не подтвердил: оборвалась
        связь посреди обмена — придёт снова. Лучше повторить дважды,
        чем потерять один раз.
        """
        acks = {'storage_requests': []}

        for item in requests:
            try:
                self._apply_storage_request(item)
                acks['storage_requests'].append(
                    {'server_id': item['server_id'], 'accepted': True})
            except Exception as e:
                self.db.rollback()
                log.error(f"Заявка на комплект не принята: {e}")
                acks['storage_requests'].append(
                    {'server_id': item['server_id'], 'accepted': False,
                     'reason': str(e)[:200]})

        return acks


    def _apply_storage_request(self, item):
        """
        Заявка «привезите комплект к дате».

        Своей таблицы под это нет, и заводить её ради одной строки
        незачем: пишем в комментарий комплекта — там кладовщик и смотрит.
        """
        from models import TireStorage

        if not item.get('storage_local_id'):
            raise ValueError('Заявка без номера комплекта')

        row = self.db.query(TireStorage).filter(
            TireStorage.id == item['storage_local_id']).first()
        if row is None:
            raise ValueError(f"Комплект №{item['storage_local_id']} не найден")

        when = _decode_time(item.get('requested_for'))
        note = (f"Клиент заказал через приложение на "
                f"{when:%d.%m.%Y %H:%M}" if when
                else 'Клиент отменил заявку через приложение')

        existing = (row.comments or '').strip()
        # Прошлые заявки не затираем: по ним видно, что человек уже
        # переносил дату, и это важно при разговоре
        row.comments = f"{existing}\n{note}".strip() if existing else note
        self.db.commit()

    # ------------------------------------------------------------------
    # Один проход обмена
    # ------------------------------------------------------------------

    def run_once(self):
        """
        Отдать своё, забрать чужое, подтвердить приём.

        Возвращает короткую сводку. Все ошибки — SyncError; вызывающий
        решает, показывать их человеку или только записать в журнал.
        """
        if not self.is_enabled():
            raise SyncError('Обмен выключен в настройках')

        # Спрашиваем сервер, что у него уже есть. Отметку держит он, а не
        # цех: сервер могли поднять заново из пустой базы, и своя отметка
        # врала бы, а история так и осталась бы с дырой
        changed_since = None
        try:
            state = self._call('GET', '/sync/state')
            changed_since = _decode_time(state.get('visits_changed_until'))
            if changed_since is not None:
                # Небольшой нахлёст: наряд могли оплатить ровно в тот миг,
                # когда прошлый обмен уже собрал данные
                changed_since -= timedelta(hours=1)
        except SyncError:
            # Не спросили — отдадим всё. Лишний трафик лучше пропажи
            pass

        pushed = self._call('POST', '/sync/push',
                            self.collect_push(changed_since))

        requests = self._call('GET', '/sync/storage-requests')
        acks = self.apply_pull(requests)

        if acks['storage_requests']:
            self._call('POST', '/sync/storage-requests/ack', acks)

        # Выплаты, отмеченные владельцем на карту
        payouts = self._call('GET', '/sync/payouts')
        payout_acks = self.apply_payouts(payouts)

        if payout_acks['payouts']:
            self._call('POST', '/sync/payouts/ack', payout_acks)

        self._settings().set(LAST_OK_KEY, get_moscow_time().isoformat())

        return {
            'sent': pushed,
            'new_storage_requests': len(requests),
            'new_payouts': len(payouts),
        }

    def run_in_background(self, on_done=None):
        """Обмен в отдельном потоке: интерфейс не должен замирать."""
        def worker():
            try:
                result = self.run_once()
                if on_done:
                    on_done(True, result)
            except SyncError as e:
                log.warning(f"Обмен не удался: {e}")
                if on_done:
                    on_done(False, str(e))
            except Exception as e:
                log.error(f"Обмен сорвался: {e}")
                if on_done:
                    on_done(False, str(e))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread


def _changed_at(order):
    """
    Когда наряд последний раз менялся.

    Оплата, возврат, удаление — три события, после которых наряд
    выглядит иначе. Берём последнее из них: по нему сервер понимает,
    что строку надо обновить, а цех — что её пора дослать.
    """
    stamps = [as_naive(order.paid_at), as_naive(order.refunded_at),
              as_naive(order.deleted_at)]
    stamps = [item for item in stamps if item is not None]
    return max(stamps) if stamps else None


def _encode(value):
    """Даты в JSON — строкой ISO."""
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    raise TypeError(f'Не знаю, как отправить {type(value)}')


def _decode_time(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return as_naive(value)
    try:
        return as_naive(datetime.fromisoformat(str(value).replace('Z', '')))
    except ValueError:
        return None
