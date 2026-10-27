"""Оформление организаций: название, цвет, логотип

Revision ID: e5b3c9a1d7f4
Revises: c7e1a5d9f3b2
Create Date: 2026-10-27 21:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5b3c9a1d7f4'
down_revision: Union[str, Sequence[str], None] = 'c7e1a5d9f3b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('brand_name', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('brand_color', sa.String(length=9), nullable=True))
        batch_op.add_column(sa.Column('logo', sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column('logo_type', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('logo_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.drop_column('logo_at')
        batch_op.drop_column('logo_type')
        batch_op.drop_column('logo')
        batch_op.drop_column('brand_color')
        batch_op.drop_column('brand_name')
