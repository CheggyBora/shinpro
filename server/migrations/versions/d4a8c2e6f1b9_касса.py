"""Касса

Приходные и расходные ордера из цеха (docs/cash.md) и пересчёт кассы
у смены: сколько было на начало, сколько должно быть, сколько
пересчитали, расхождение и его причина. Ордер узнаём по uid цеха,
уникальному внутри точки.

У старых смен полей кассы нет — они остаются пустыми: пустое значит
«не считали», а не ноль.

Revision ID: d4a8c2e6f1b9
Revises: b3e9d1f7a2c5
Create Date: 2026-10-26 23:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4a8c2e6f1b9'
down_revision: Union[str, Sequence[str], None] = 'b3e9d1f7a2c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cash_orders',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('shop_id', sa.Integer(), nullable=False),
        sa.Column('uid', sa.String(length=40), nullable=False),
        sa.Column('kind', sa.String(length=4), nullable=False,
                  server_default='out'),
        sa.Column('number', sa.Integer(), nullable=True),
        sa.Column('category', sa.String(length=60), nullable=True),
        sa.Column('amount', sa.Float(), nullable=False, server_default='0'),
        sa.Column('method', sa.String(length=10), nullable=False,
                  server_default='cash'),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('employee_local_id', sa.Integer(), nullable=True),
        sa.Column('shift_local_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('reverses_uid', sa.String(length=40), nullable=True),
        sa.Column('payout_local_id', sa.Integer(), nullable=True),
        sa.Column('changed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shop_id', 'uid', name='uq_cash_orders_shop_uid'),
    )
    with op.batch_alter_table('cash_orders', schema=None) as batch_op:
        batch_op.create_index('ix_cash_orders_shop_id', ['shop_id'],
                              unique=False)
        batch_op.create_index('ix_cash_orders_created_at', ['created_at'],
                              unique=False)

    with op.batch_alter_table('shop_shifts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cash_start', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('cash_expected', sa.Float(),
                                      nullable=True))
        batch_op.add_column(sa.Column('cash_counted', sa.Float(),
                                      nullable=True))
        batch_op.add_column(sa.Column('cash_diff', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('cash_diff_reason',
                                      sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('shop_shifts', schema=None) as batch_op:
        batch_op.drop_column('cash_diff_reason')
        batch_op.drop_column('cash_diff')
        batch_op.drop_column('cash_counted')
        batch_op.drop_column('cash_expected')
        batch_op.drop_column('cash_start')

    with op.batch_alter_table('cash_orders', schema=None) as batch_op:
        batch_op.drop_index('ix_cash_orders_created_at')
        batch_op.drop_index('ix_cash_orders_shop_id')
    op.drop_table('cash_orders')
