from sqlalchemy import Column, Integer, Date

from config import Base


class BookingPosts(Base):
    """
    Сколько постов открыто под предварительную запись на конкретный день.

    Это не то же самое, что посты в смене: в смене они считаются по факту
    работы, а здесь приёмщик заранее решает, сколько машин он готов
    пообещать на день. В понедельник может работать один мастер, в субботу
    три — и записывать нужно по-разному.

    Дня нет в таблице — значит, пост один: пообещать больше, чем реально
    сделаешь, хуже, чем открыть ещё один пост в середине дня.
    """
    __tablename__ = 'booking_posts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    day = Column(Date, unique=True, nullable=False, index=True)
    posts = Column(Integer, nullable=False, default=1)

    def __repr__(self):
        return f"<BookingPosts {self.day} = {self.posts}>"
