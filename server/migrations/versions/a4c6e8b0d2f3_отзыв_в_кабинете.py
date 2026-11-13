"""Отзыв в кабинете клиента: клиент закрыл карточку

Revision ID: a4c6e8b0d2f3
Revises: f3b5d7a9c1e2
Create Date: 2026-11-13 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a4c6e8b0d2f3'
down_revision: Union[str, Sequence[str], None] = 'f3b5d7a9c1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('visits') as batch:
        batch.add_column(sa.Column('review_closed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('visits') as batch:
        batch.drop_column('review_closed_at')
