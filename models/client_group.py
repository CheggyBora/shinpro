from sqlalchemy import Column, Integer, String
from config import Base


class ClientGroup(Base):
    """
    Внутренняя группа клиента: кому можно предлагать допы, а с кем
    лучше ограничиться тем, за чем приехал.

    Это мнение цеха о человеке, и оно никогда не уходит с компьютера
    цеха: ни на сервер, ни в личный кабинет, ни на чек. Поэтому группы
    лежат отдельной таблицей, а не в настройках — часть настроек
    уезжает на сервер при обмене.

    На экране группа обозначена только кодом (11, 22 …). Клиент,
    заглянувший в монитор, увидит число и ничего из него не поймёт.
    """
    __tablename__ = 'client_groups'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Что видно в окошке: «11». Порядок групп — по коду
    code = Column(String(10), nullable=False, unique=True)

    # Для своих: «Очень лояльный»
    title = Column(String(100), nullable=False)

    # Как с таким говорить: «Предлагать смело — балансировку, хранение»
    hint = Column(String(300), nullable=True)

    def __repr__(self):
        return f"<ClientGroup {self.code} {self.title}>"
