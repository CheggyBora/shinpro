"""Запись: «я на месте» и вызов на пост

Revision ID: 8d2e4f6a1c3b
Revises: 5a7c0e1d2b9f
Create Date: 2026-10-18 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8d2e4f6a1c3b'
down_revision: Union[str, Sequence[str], None] = '5a7c0e1d2b9f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('appointments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('on_site_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('called_post', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('called_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('appointments', schema=None) as batch_op:
        batch_op.drop_column('called_at')
        batch_op.drop_column('called_post')
        batch_op.drop_column('on_site_at')
