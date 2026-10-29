"""Время создания наряда

Дашборд показывал только, когда наряд пробит. Теперь цех присылает и
когда он создан (решение владельца 29.10.2026). Старые наряды этого не
знают — колонка пустая.

Revision ID: e9a1c3f5b7d2
Revises: d2e7a9c4b6f1
Create Date: 2026-10-29 19:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e9a1c3f5b7d2'
down_revision: Union[str, Sequence[str], None] = 'd2e7a9c4b6f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('visits', schema=None) as batch_op:
        batch_op.add_column(sa.Column('opened_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('visits', schema=None) as batch_op:
        batch_op.drop_column('opened_at')
