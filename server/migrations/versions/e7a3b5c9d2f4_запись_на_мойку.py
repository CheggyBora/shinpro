"""Запись на мойку

У записи появилось направление — шиномонтаж или мойка — и класс машины
для мойки. Всё, что лежало до этого шага, — шиномонтаж: мойку тогда
не записывали, поэтому старые строки получают «tire» прямо в базе
(docs/booking_wash.md).

Revision ID: e7a3b5c9d2f4
Revises: c4d8a2f6e1b3
Create Date: 2026-10-26 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7a3b5c9d2f4'
down_revision: Union[str, Sequence[str], None] = 'c4d8a2f6e1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('appointments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('direction', sa.String(length=10),
                                      nullable=False, server_default='tire'))
        batch_op.add_column(sa.Column('wash_class', sa.String(length=16),
                                      nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('appointments', schema=None) as batch_op:
        batch_op.drop_column('wash_class')
        batch_op.drop_column('direction')
