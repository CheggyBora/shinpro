"""Календарь задач и контрагенты

Задачи ставят с двух сторон — в цеху и из дашборда, — и обе стороны
меняют одну и ту же строку. Поэтому у задачи свой uid, общий для цеха
и сервера, и время правки, по которому решается, чья правка новее
(docs/calendar.md).

Revision ID: 7b4e2c9d1f05
Revises: 3c6b1e9a7d42
Create Date: 2026-10-24 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7b4e2c9d1f05'
down_revision: Union[str, Sequence[str], None] = '3c6b1e9a7d42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tasks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('shop_id', sa.Integer(), nullable=False),
        sa.Column('uid', sa.String(length=40), nullable=False),
        sa.Column('category', sa.String(length=10), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('due_time', sa.String(length=5), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('license_plate', sa.String(length=20), nullable=True),
        sa.Column('client_name', sa.String(length=200), nullable=True),
        sa.Column('client_phone', sa.String(length=20), nullable=True),
        sa.Column('counterparty_uid', sa.String(length=40), nullable=True),
        sa.Column('storage_ref', sa.String(length=100), nullable=True),
        sa.Column('amount', sa.Float(), nullable=True),
        sa.Column('done_at', sa.DateTime(), nullable=True),
        sa.Column('done_by', sa.String(length=100), nullable=True),
        sa.Column('deleted', sa.Boolean(), nullable=False,
                  server_default='0'),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('created_by', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shop_id', 'uid', name='uq_tasks_shop_uid'),
    )
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.create_index('ix_tasks_shop_id', ['shop_id'], unique=False)
        batch_op.create_index('ix_tasks_shop_updated',
                              ['shop_id', 'updated_at'], unique=False)
        batch_op.create_index('ix_tasks_shop_due',
                              ['shop_id', 'due_date'], unique=False)

    op.create_table(
        'counterparties',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('shop_id', sa.Integer(), nullable=False),
        sa.Column('uid', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('kind', sa.String(length=200), nullable=True),
        sa.Column('contact', sa.String(length=200), nullable=True),
        sa.Column('phone', sa.String(length=40), nullable=True),
        sa.Column('email', sa.String(length=200), nullable=True),
        sa.Column('address', sa.String(length=300), nullable=True),
        sa.Column('inn', sa.String(length=20), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('deleted', sa.Boolean(), nullable=False,
                  server_default='0'),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shop_id', 'uid',
                            name='uq_counterparties_shop_uid'),
    )
    with op.batch_alter_table('counterparties', schema=None) as batch_op:
        batch_op.create_index('ix_counterparties_shop_id', ['shop_id'],
                              unique=False)
        batch_op.create_index('ix_counterparties_shop_updated',
                              ['shop_id', 'updated_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('counterparties', schema=None) as batch_op:
        batch_op.drop_index('ix_counterparties_shop_updated')
        batch_op.drop_index('ix_counterparties_shop_id')
    op.drop_table('counterparties')

    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_index('ix_tasks_shop_due')
        batch_op.drop_index('ix_tasks_shop_updated')
        batch_op.drop_index('ix_tasks_shop_id')
    op.drop_table('tasks')
