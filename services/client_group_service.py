"""
Внутренние группы клиентов: кому предлагать допы, а кому нет.

Приёмщик ставит группу после визита, а в следующий раз видит её до
первого слова. Сама группа на экране не написана: в наряде стоит
неприметный значок, и только по нажатию открывается окошко с кодом.
Клиент у стойки не увидит ничего — ни слова «негатив», ни цвета.

Группы настраиваются: свои коды, названия и подсказка, как говорить.
По умолчанию пять — от 11 (очень лояльный) до 55 (негатив).

Ничего отсюда не уходит с компьютера цеха. В обмен с сервером группа
не попадает, поэтому её нет ни в личном кабинете, ни в дашборде.
"""
from sqlalchemy.orm import Session

from models import Client, ClientGroup
from utils import get_moscow_time

# Отметка, что группы по умолчанию уже заводили. Без неё удалённые
# владельцем группы возвращались бы при каждом запуске
SEEDED_KEY = 'client_groups_seeded'

DEFAULT_GROUPS = [
    ('11', 'Очень лояльный',
     'Предлагать смело: балансировку, хранение, вентили, всё по делу'),
    ('22', 'Лояльный',
     'Предлагать то, что действительно нужно машине'),
    ('33', 'Обычный',
     'Предложить одно главное, не настаивать'),
    ('44', 'Сложный',
     'Только то, за чем приехал. Цены называть заранее'),
    ('55', 'Негатив',
     'Ничего сверх не предлагать. Сделать, рассчитать, отпустить'),
]


class ClientGroupService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Группы
    # ------------------------------------------------------------------

    def ensure_defaults(self):
        """Завести группы по умолчанию — один раз за жизнь базы."""
        from services.settings_service import SettingsService

        settings = SettingsService(self.db)
        if settings.get(SEEDED_KEY) == '1':
            return

        if not self.db.query(ClientGroup).count():
            for code, title, hint in DEFAULT_GROUPS:
                self.db.add(ClientGroup(code=code, title=title, hint=hint))
        settings.set(SEEDED_KEY, '1', commit=False)
        self.db.commit()

    def groups(self):
        """Все группы по порядку кода: 11, 22, 33 …"""
        self.ensure_defaults()
        rows = self.db.query(ClientGroup).all()
        # Коды — строки, но по смыслу числа: «9» должен идти раньше «11»
        return sorted(rows, key=lambda g: (len(g.code), g.code))

    def get(self, group_id):
        if group_id is None:
            return None
        return self.db.query(ClientGroup).filter(
            ClientGroup.id == group_id).first()

    def _clean(self, code, title, hint, skip_id=None):
        code = (code or '').strip()
        title = (title or '').strip()
        hint = (hint or '').strip() or None

        if not code:
            raise ValueError('Укажите код группы, например 11')
        if len(code) > 10:
            raise ValueError('Код слишком длинный — хватит двух-трёх знаков')
        if not title:
            raise ValueError('Укажите название группы')

        same = self.db.query(ClientGroup).filter(ClientGroup.code == code)
        if skip_id is not None:
            same = same.filter(ClientGroup.id != skip_id)
        if same.first():
            raise ValueError(f'Группа с кодом {code} уже есть')

        return code, title, hint

    def add(self, code, title, hint=None):
        self.ensure_defaults()
        code, title, hint = self._clean(code, title, hint)
        group = ClientGroup(code=code, title=title, hint=hint)
        self.db.add(group)
        self.db.commit()
        return group

    def update(self, group_id, code, title, hint=None):
        group = self.get(group_id)
        if group is None:
            raise ValueError('Группа не найдена')
        group.code, group.title, group.hint = self._clean(
            code, title, hint, skip_id=group_id)
        self.db.commit()
        return group

    def count_clients(self, group_id):
        return self.db.query(Client).filter(
            Client.group_id == group_id).count()

    def delete(self, group_id):
        """
        Удалить группу. Клиенты из неё остаются без группы — переносить
        их молча в соседнюю нельзя: 44 и 55 значат разное.
        """
        group = self.get(group_id)
        if group is None:
            return 0
        moved = self.db.query(Client).filter(
            Client.group_id == group_id).update(
                {Client.group_id: None, Client.group_set_at: None},
                synchronize_session=False)
        self.db.delete(group)
        self.db.commit()
        return moved

    # ------------------------------------------------------------------
    # Клиент
    # ------------------------------------------------------------------

    def group_of(self, client_id):
        """Группа клиента или None."""
        client = self.db.query(Client).filter(Client.id == client_id).first()
        if client is None or client.group_id is None:
            return None
        return self.get(client.group_id)

    def set_group(self, client_id, group_id):
        """Поставить группу (или снять — group_id=None). Прав последний."""
        client = self.db.query(Client).filter(Client.id == client_id).first()
        if client is None:
            raise ValueError('Клиент не найден')
        if group_id is not None and self.get(group_id) is None:
            raise ValueError('Такой группы уже нет')

        if client.group_id == group_id:
            return client

        client.group_id = group_id
        client.group_set_at = get_moscow_time() if group_id is not None else None
        self.db.commit()
        return client
