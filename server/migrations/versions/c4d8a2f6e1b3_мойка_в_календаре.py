"""Мойка: свой слой календаря

У задачи и контрагента появилось направление — шиномонтаж или мойка.
Всё, что лежало до этого шага, — шиномонтаж: мойки тогда не было,
поэтому старые строки получают «tire» прямо в базе, без перебора
(docs/calendar.md, «Мойка: свой слой календаря»).

Revision ID: c4d8a2f6e1b3
Revises: 7b4e2c9d1f05
Create Date: 2026-10-26 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d8a2f6e1b3'
down_revision: Union[str, Sequence[str], None] = '7b4e2c9d1f05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ('tasks', 'counterparties'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('direction', sa.String(length=10),
                                          nullable=False,
                                          server_default='tire'))


def downgrade() -> None:
    for table in ('counterparties', 'tasks'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column('direction')
