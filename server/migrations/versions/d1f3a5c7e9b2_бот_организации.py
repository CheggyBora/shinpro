"""Бот организации на сервере: кто писал боту

Revision ID: d1f3a5c7e9b2
Revises: c8e2a4f6b9d3
Create Date: 2026-11-13 06:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd1f3a5c7e9b2'
down_revision: Union[str, Sequence[str], None] = 'c8e2a4f6b9d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'telegram_chats',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('chat_id', sa.String(length=32), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('last_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'chat_id', name='uq_telegram_chats_account_chat'))
    op.create_index('ix_telegram_chats_account_id', 'telegram_chats', ['account_id'])


def downgrade() -> None:
    op.drop_index('ix_telegram_chats_account_id', table_name='telegram_chats')
    op.drop_table('telegram_chats')
