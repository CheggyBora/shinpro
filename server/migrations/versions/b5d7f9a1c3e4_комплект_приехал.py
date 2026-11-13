"""Комплект привезли со склада: время приезда

Revision ID: b5d7f9a1c3e4
Revises: a4c6e8b0d2f3
Create Date: 2026-11-13 16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b5d7f9a1c3e4'
down_revision: Union[str, Sequence[str], None] = 'a4c6e8b0d2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('stored_sets') as batch:
        batch.add_column(sa.Column('arrived_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('stored_sets') as batch:
        batch.drop_column('arrived_at')
