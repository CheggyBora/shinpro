"""Коды подключения точек и неверные попытки

Revision ID: f8d2a6c4e9b1
Revises: e5b3c9a1d7f4
Create Date: 2026-10-27 23:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f8d2a6c4e9b1'
down_revision: Union[str, Sequence[str], None] = 'e5b3c9a1d7f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'connect_codes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('shop_id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=8), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id']),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_connect_codes_shop_id', 'connect_codes', ['shop_id'])
    op.create_index('ix_connect_codes_code', 'connect_codes', ['code'])

    op.create_table(
        'connect_attempts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('address', sa.String(length=64), nullable=False),
        sa.Column('at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_connect_attempts_address', 'connect_attempts', ['address'])
    op.create_index('ix_connect_attempts_at', 'connect_attempts', ['at'])


def downgrade() -> None:
    op.drop_index('ix_connect_attempts_at', table_name='connect_attempts')
    op.drop_index('ix_connect_attempts_address', table_name='connect_attempts')
    op.drop_table('connect_attempts')
    op.drop_index('ix_connect_codes_code', table_name='connect_codes')
    op.drop_index('ix_connect_codes_shop_id', table_name='connect_codes')
    op.drop_table('connect_codes')
