"""Склад точки

Остатки ведёт цех и присылает снимком целиком: что пришло — то и
лежит, чего нет в снимке — удалено (docs/stock.md). Позицию узнаём по
uid цеха, уникальному внутри точки.

Revision ID: a6f2c8e4b1d7
Revises: e7a3b5c9d2f4
Create Date: 2026-10-26 21:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a6f2c8e4b1d7'
down_revision: Union[str, Sequence[str], None] = 'e7a3b5c9d2f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'stock_items',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('shop_id', sa.Integer(), nullable=False),
        sa.Column('uid', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('direction', sa.String(length=10), nullable=False,
                  server_default='tire'),
        sa.Column('kind', sa.String(length=10), nullable=False,
                  server_default='material'),
        sa.Column('unit', sa.String(length=10), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('min_quantity', sa.Float(), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('purchase_price', sa.Float(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shop_id', 'uid', name='uq_stock_items_shop_uid'),
    )
    with op.batch_alter_table('stock_items', schema=None) as batch_op:
        batch_op.create_index('ix_stock_items_shop_id', ['shop_id'],
                              unique=False)


def downgrade() -> None:
    with op.batch_alter_table('stock_items', schema=None) as batch_op:
        batch_op.drop_index('ix_stock_items_shop_id')
    op.drop_table('stock_items')
