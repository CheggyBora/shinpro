"""Отзывы клиентов: ссылки организации, отметка в наряде

Revision ID: f3b5d7a9c1e2
Revises: e2a4c6b8d0f1
Create Date: 2026-11-13 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3b5d7a9c1e2'
down_revision: Union[str, Sequence[str], None] = 'e2a4c6b8d0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('accounts') as batch:
        batch.add_column(sa.Column('review_links', sa.Text(), nullable=True))
    with op.batch_alter_table('visits') as batch:
        batch.add_column(sa.Column('ask_review', sa.Boolean(), nullable=True))
        batch.add_column(sa.Column('review_planned_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('warranty_of_local_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('visits') as batch:
        batch.drop_column('warranty_of_local_id')
        batch.drop_column('review_planned_at')
        batch.drop_column('ask_review')
    with op.batch_alter_table('accounts') as batch:
        batch.drop_column('review_links')
