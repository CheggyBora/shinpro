from sqlalchemy import Column, Integer, Float, String, DateTime
from config import Base
from utils import get_moscow_time

class Shift(Base):
    __tablename__ = 'shifts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    start_time = Column(DateTime(timezone=True), default=get_moscow_time)
    end_time = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), default='open')
    total_salary = Column(Float, default=0.0)

    # Сколько постов открыто в эту смену. От этого зависит, сколько машин
    # обслуживается одновременно, а значит расчёт очереди и записи.
    # Закрыли пост — он просто выпадает из расчёта.
    open_posts = Column(Integer, default=2, nullable=False)
