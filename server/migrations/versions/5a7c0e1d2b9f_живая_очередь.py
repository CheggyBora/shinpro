"""Живая очередь по QR и диаметр в записи

Revision ID: 5a7c0e1d2b9f
Revises: 29d414f3609c
Create Date: 2026-10-18 17:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5a7c0e1d2b9f'
down_revision: Union[str, Sequence[str], None] = '29d414f3609c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'live_tickets',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('shop_id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=True),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('license_plate', sa.String(length=20), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('wheel_diameter', sa.String(length=10), nullable=True),
        sa.Column('wheels_assembled', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('state', sa.String(length=10), nullable=False,
                  server_default='waiting'),
        sa.Column('local_id', sa.Integer(), nullable=True),
        sa.Column('place', sa.Integer(), nullable=True),
        sa.Column('eta_at', sa.DateTime(), nullable=True),
        sa.Column('post_number', sa.Integer(), nullable=True),
        sa.Column('called_at', sa.DateTime(), nullable=True),
        sa.Column('told_at', sa.DateTime(), nullable=True),
        sa.Column('left_by_client', sa.Boolean(), nullable=False,
                  server_default='0'),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id']),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('live_tickets', schema=None) as batch_op:
        batch_op.create_index('ix_live_tickets_shop_id', ['shop_id'], unique=False)
        batch_op.create_index('ix_live_tickets_token', ['token'], unique=True)
        batch_op.create_index('ix_live_tickets_shop_state', ['shop_id', 'state'],
                              unique=False)

    # Диаметр в онлайн-записи: наряд по приезду открывается сразу с
    # ценами пакета
    with op.batch_alter_table('appointments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('wheel_diameter', sa.String(length=10),
                                      nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('appointments', schema=None) as batch_op:
        batch_op.drop_column('wheel_diameter')
    with op.batch_alter_table('live_tickets', schema=None) as batch_op:
        batch_op.drop_index('ix_live_tickets_shop_state')
        batch_op.drop_index('ix_live_tickets_token')
        batch_op.drop_index('ix_live_tickets_shop_id')
    op.drop_table('live_tickets')
