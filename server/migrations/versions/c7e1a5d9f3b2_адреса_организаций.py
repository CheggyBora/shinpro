"""Адреса организаций

У каждой организации свой сайт записи и свой дашборд: по адресу
сервер понимает, чей это кабинет. Наш поддомен заводится сразу, свой
домен организация подключает сама.

Revision ID: c7e1a5d9f3b2
Revises: a9c4e2f7b3d1
Create Date: 2026-10-27 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7e1a5d9f3b2'
down_revision: Union[str, Sequence[str], None] = 'a9c4e2f7b3d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'account_domains',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=253), nullable=False),
        sa.Column('role', sa.String(length=8), nullable=False),
        sa.Column('kind', sa.String(length=8), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.Column('checked_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_account_domains_account_id', 'account_domains', ['account_id'])
    op.create_index('ix_account_domains_name', 'account_domains', ['name'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_account_domains_name', table_name='account_domains')
    op.drop_index('ix_account_domains_account_id', table_name='account_domains')
    op.drop_table('account_domains')
