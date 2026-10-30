"""Номер машины — до 50 знаков, как в программе цеха

В цеху номер машины хранится до 50 знаков, на сервере было 20. Машина
с длинным номером («БЕЗ НОМЕРА …», иностранный, с пометкой) роняла весь
обмен точки с ошибкой 500 — и вместе с ним не доезжали настройки, в том
числе ключ звонков (30.10.2026).

Revision ID: b5d9f3a7c1e4
Revises: a3c7e1f9d5b2
Create Date: 2026-10-30 22:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b5d9f3a7c1e4'
down_revision: Union[str, Sequence[str], None] = 'a3c7e1f9d5b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = [
    ('cars', 'license_plate', False),
    ('live_tickets', 'license_plate', False),
    ('open_orders', 'license_plate', False),
    ('order_photos', 'license_plate', True),
    ('work_offers', 'license_plate', True),
    ('arrivals', 'plate', False),
    ('appointments', 'license_plate', True),
    ('stored_sets', 'license_plate', True),
    ('visits', 'license_plate', True),
    ('tasks', 'license_plate', True),
]


def _resize(length_from, length_to):
    for table, column, nullable in COLUMNS:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column(column, existing_type=sa.String(length_from),
                                  type_=sa.String(length_to),
                                  existing_nullable=nullable)


def upgrade() -> None:
    _resize(20, 50)


def downgrade() -> None:
    _resize(50, 20)
