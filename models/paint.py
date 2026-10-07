"""
Покраска дисков: дополнения к базовой работе.

Покраска считается не как шиномонтаж. Там цена зависит от диаметра и
всё; здесь к базовой покраске добавляются работы, которые клиент
выбирает: проточка, кант, два цвета, логотип. Поэтому прайсом это не
описать — нужен счёт, который складывает выбранное.

Базовая цена живёт в настройках по диаметрам, как у хранения. Здесь —
только то, что к ней добавляется.
"""
from sqlalchemy import Column, Integer, String, Float, Boolean

from config import Base


class PaintOption(Base):
    """Одно дополнение к покраске."""
    __tablename__ = 'paint_options'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    price = Column(Float, default=0.0, nullable=False)

    # За колесо или за весь заказ. Проточка — за колесо, покраска
    # суппортов — за машину целиком, и складывать их одинаково нельзя
    per_wheel = Column(Boolean, default=True, nullable=False)

    # Короткое пояснение под названием: зачем это нужно клиенту.
    # Приёмщик по телефону объясняет одно и то же по десять раз
    note = Column(String(300), nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)

    # Порядок в списке. Задаётся руками: самое ходовое должно быть
    # сверху, а не то, что завели первым
    position = Column(Integer, default=100, nullable=False)
