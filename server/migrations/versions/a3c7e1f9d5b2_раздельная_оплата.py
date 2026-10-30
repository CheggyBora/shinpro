"""Раздельная оплата

Часть наличными, часть картой (решение владельца 30.10.2026): у наряда
способ оплаты mixed, а здесь — сколько наличными. Картой — остаток.

Revision ID: a3c7e1f9d5b2
Revises: f4b8d2a6c1e9
Create Date: 2026-10-30 19:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3c7e1f9d5b2'
down_revision: Union[str, Sequence[str], None] = 'f4b8d2a6c1e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('visits', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cash_amount', sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('visits', schema=None) as batch_op:
        batch_op.drop_column('cash_amount')
