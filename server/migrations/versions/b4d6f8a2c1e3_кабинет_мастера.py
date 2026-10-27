"""Кабинет мастера: вход по ПИН, видео, состав наряда, прайс, согласования

Revision ID: b4d6f8a2c1e3
Revises: f8d2a6c4e9b1
Create Date: 2026-10-27 23:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b4d6f8a2c1e3'
down_revision: Union[str, Sequence[str], None] = 'f8d2a6c4e9b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('master_devices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('employee_local_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('pin_fails', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('locked_until', sa.DateTime(), nullable=True))

    with op.batch_alter_table('shop_employees', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pin_hash', sa.String(length=64), nullable=True))

    with op.batch_alter_table('open_orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('masters', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('car', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('client_name', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('wheel_diameter', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('wash_class', sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column('directions', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('services', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('post', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('finished_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('told_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('order_photos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('media', sa.String(length=8), server_default='photo', nullable=False))
        batch_op.add_column(sa.Column('content_type', sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column('size', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('employee_local_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('viewed_at', sa.DateTime(), nullable=True))

    op.create_table(
        'shop_services',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('shop_id', sa.Integer(), nullable=False),
        sa.Column('local_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('direction', sa.String(length=10), nullable=False),
        sa.Column('prices', sa.Text(), nullable=True),
        sa.Column('editable', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id']),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_shop_services_shop_id', 'shop_services', ['shop_id'])

    op.create_table(
        'work_offers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('shop_id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=True),
        sa.Column('order_local_id', sa.Integer(), nullable=False),
        sa.Column('license_plate', sa.String(length=20), nullable=True),
        sa.Column('photo_id', sa.Integer(), nullable=True),
        sa.Column('items', sa.Text(), nullable=False),
        sa.Column('total', sa.Integer(), nullable=False),
        sa.Column('comment', sa.String(length=500), nullable=True),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('employee_local_id', sa.Integer(), nullable=True),
        sa.Column('author', sa.String(length=80), nullable=True),
        sa.Column('state', sa.String(length=10), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('channel', sa.String(length=16), nullable=True),
        sa.Column('last_error', sa.String(length=255), nullable=True),
        sa.Column('answered_at', sa.DateTime(), nullable=True),
        sa.Column('taken_at', sa.DateTime(), nullable=True),
        sa.Column('reminded_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id']),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id']),
        sa.ForeignKeyConstraint(['photo_id'], ['order_photos.id']),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_work_offers_shop_id', 'work_offers', ['shop_id'])
    op.create_index('ix_work_offers_client_id', 'work_offers', ['client_id'])
    op.create_index('ix_work_offers_order_local_id', 'work_offers', ['order_local_id'])
    op.create_index('ix_work_offers_token', 'work_offers', ['token'], unique=True)
    op.create_index('ix_work_offers_created_at', 'work_offers', ['created_at'])

    op.create_table(
        'master_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('shop_id', sa.Integer(), nullable=False),
        sa.Column('order_local_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('employee_local_id', sa.Integer(), nullable=True),
        sa.Column('author', sa.String(length=80), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('told', sa.Boolean(), nullable=False),
        sa.Column('taken_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id']),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_master_events_shop_id', 'master_events', ['shop_id'])
    op.create_index('ix_master_events_taken_at', 'master_events', ['taken_at'])


def downgrade() -> None:
    op.drop_index('ix_master_events_taken_at', table_name='master_events')
    op.drop_index('ix_master_events_shop_id', table_name='master_events')
    op.drop_table('master_events')
    for name in ('created_at', 'token', 'order_local_id', 'client_id', 'shop_id'):
        op.drop_index(f'ix_work_offers_{name}', table_name='work_offers')
    op.drop_table('work_offers')
    op.drop_index('ix_shop_services_shop_id', table_name='shop_services')
    op.drop_table('shop_services')

    with op.batch_alter_table('order_photos', schema=None) as batch_op:
        for name in ('viewed_at', 'employee_local_id', 'size', 'content_type', 'media'):
            batch_op.drop_column(name)
    with op.batch_alter_table('open_orders', schema=None) as batch_op:
        for name in ('told_at', 'finished_at', 'post', 'services', 'directions',
                     'wash_class', 'wheel_diameter', 'client_name', 'car', 'masters'):
            batch_op.drop_column(name)
    with op.batch_alter_table('shop_employees', schema=None) as batch_op:
        batch_op.drop_column('pin_hash')
    with op.batch_alter_table('master_devices', schema=None) as batch_op:
        for name in ('locked_until', 'pin_fails', 'employee_local_id'):
            batch_op.drop_column(name)
