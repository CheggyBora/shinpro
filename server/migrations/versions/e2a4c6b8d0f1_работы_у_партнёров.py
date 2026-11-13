"""Работы у партнёров: поля задачи, переписка, цена клиенту, кто согласует

Revision ID: e2a4c6b8d0f1
Revises: d1f3a5c7e9b2
Create Date: 2026-11-13 08:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e2a4c6b8d0f1'
down_revision: Union[str, Sequence[str], None] = 'd1f3a5c7e9b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('tasks') as batch:
        batch.add_column(sa.Column('partner_kind', sa.String(length=10), nullable=True))
        batch.add_column(sa.Column('partner_status', sa.String(length=12), nullable=True))
        batch.add_column(sa.Column('our_price', sa.Float(), nullable=True))
        batch.add_column(sa.Column('partner_price', sa.Float(), nullable=True))
        batch.add_column(sa.Column('needs_client', sa.Boolean(), nullable=True))
        batch.add_column(sa.Column('order_local_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('pay_method', sa.String(length=10), nullable=True))
        batch.add_column(sa.Column('pay_note', sa.String(length=300), nullable=True))
        batch.add_column(sa.Column('paid_at', sa.DateTime(), nullable=True))
    with op.batch_alter_table('counterparties') as batch:
        batch.add_column(sa.Column('telegram_chat_id', sa.String(length=32), nullable=True))
    with op.batch_alter_table('shop_employees') as batch:
        batch.add_column(sa.Column('can_partners', sa.Boolean(), nullable=False,
                                   server_default='0'))
    with op.batch_alter_table('telegram_chats') as batch:
        batch.add_column(sa.Column('pending', sa.String(length=60), nullable=True))

    op.create_table(
        'partner_messages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('shop_id', sa.Integer(), nullable=False),
        sa.Column('task_uid', sa.String(length=40), nullable=False),
        sa.Column('author', sa.String(length=10), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=True),
        sa.Column('text', sa.Text(), nullable=True),
        sa.Column('photo', sa.String(length=200), nullable=True),
        sa.Column('telegram_message_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id']),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_partner_messages_shop_id', 'partner_messages', ['shop_id'])
    op.create_index('ix_partner_messages_task_uid', 'partner_messages', ['task_uid'])

    op.create_table(
        'partner_quotes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('shop_id', sa.Integer(), nullable=False),
        sa.Column('task_uid', sa.String(length=40), nullable=False),
        sa.Column('token', sa.String(length=40), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('state', sa.String(length=10), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('answered_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id']),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_partner_quotes_shop_id', 'partner_quotes', ['shop_id'])
    op.create_index('ix_partner_quotes_task_uid', 'partner_quotes', ['task_uid'])
    op.create_index('ix_partner_quotes_token', 'partner_quotes', ['token'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_partner_quotes_token', table_name='partner_quotes')
    op.drop_index('ix_partner_quotes_task_uid', table_name='partner_quotes')
    op.drop_index('ix_partner_quotes_shop_id', table_name='partner_quotes')
    op.drop_table('partner_quotes')
    op.drop_index('ix_partner_messages_task_uid', table_name='partner_messages')
    op.drop_index('ix_partner_messages_shop_id', table_name='partner_messages')
    op.drop_table('partner_messages')
    with op.batch_alter_table('telegram_chats') as batch:
        batch.drop_column('pending')
    with op.batch_alter_table('shop_employees') as batch:
        batch.drop_column('can_partners')
    with op.batch_alter_table('counterparties') as batch:
        batch.drop_column('telegram_chat_id')
    with op.batch_alter_table('tasks') as batch:
        for name in ('paid_at', 'pay_note', 'pay_method', 'order_local_id', 'needs_client',
                     'partner_price', 'our_price', 'partner_status', 'partner_kind'):
            batch.drop_column(name)
