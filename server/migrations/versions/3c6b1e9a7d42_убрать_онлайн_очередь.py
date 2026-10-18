"""Убрать онлайн-очередь «из дома»

Её заменила живая очередь по QR (live_tickets). Талоны старой очереди
никто больше не читает и не пишет, а отметка «машина на посту
онлайн-очереди» в open_orders осталась без смысла.

Откат возвращает таблицу и колонку ровно такими, какими их создал
29d414f3609c: иначе его собственный откат упадёт на несуществующей
таблице, и до базы с нуля не дойти. Данные талонов при этом не
возвращаются — их уже нет.

Revision ID: 3c6b1e9a7d42
Revises: 8d2e4f6a1c3b
Create Date: 2026-10-18 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3c6b1e9a7d42'
down_revision: Union[str, Sequence[str], None] = '8d2e4f6a1c3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('open_orders', schema=None) as batch_op:
        batch_op.drop_column('on_queue_post')

    with op.batch_alter_table('queue_tickets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_queue_tickets_state'))
        batch_op.drop_index('ix_queue_tickets_shop_state')
        batch_op.drop_index(batch_op.f('ix_queue_tickets_shop_id'))
        batch_op.drop_index(batch_op.f('ix_queue_tickets_eta_at'))
        batch_op.drop_index(batch_op.f('ix_queue_tickets_created_at'))
        batch_op.drop_index(batch_op.f('ix_queue_tickets_client_id'))

    op.drop_table('queue_tickets')


def downgrade() -> None:
    op.create_table(
        'queue_tickets',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('shop_id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=True),
        sa.Column('license_plate', sa.String(length=20), nullable=True),
        sa.Column('client_name', sa.String(length=120), nullable=True),
        sa.Column('client_phone', sa.String(length=20), nullable=True),
        sa.Column('wheels_assembled', sa.Integer(), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('eta_at', sa.DateTime(), nullable=False),
        sa.Column('arrived_at', sa.DateTime(), nullable=True),
        sa.Column('promised_at', sa.DateTime(), nullable=True),
        sa.Column('promise_told_at', sa.DateTime(), nullable=True),
        sa.Column('moves', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(length=16), nullable=False),
        sa.Column('called_at', sa.DateTime(), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.Column('order_local_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('queue_tickets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_queue_tickets_client_id'), ['client_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_queue_tickets_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_queue_tickets_eta_at'), ['eta_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_queue_tickets_shop_id'), ['shop_id'], unique=False)
        batch_op.create_index('ix_queue_tickets_shop_state', ['shop_id', 'state'], unique=False)
        batch_op.create_index(batch_op.f('ix_queue_tickets_state'), ['state'], unique=False)

    with op.batch_alter_table('open_orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('on_queue_post', sa.Boolean(),
                                      nullable=False,
                                      server_default=sa.false()))
