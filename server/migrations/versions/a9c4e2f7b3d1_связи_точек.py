"""Связи точек с клиентами и машинами

Номера строк у каждой точки свои: клиент №5 одной точки и №5 другой —
разные люди. Связь «точка + номер строки → клиент (машина)» держим в
отдельных таблицах. Уже известные связи переносим к первой точке
аккаунта — до этого шага у аккаунтов была одна рабочая точка, и
клиенты пришли из неё.

Revision ID: a9c4e2f7b3d1
Revises: f6b2d8a4c9e1
Create Date: 2026-10-27 02:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a9c4e2f7b3d1'
down_revision: Union[str, Sequence[str], None] = 'f6b2d8a4c9e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'shop_clients',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('shop_id', sa.Integer(), nullable=False),
        sa.Column('local_id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id']),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shop_id', 'local_id', name='uq_shop_clients_local'),
    )
    op.create_index('ix_shop_clients_shop_id', 'shop_clients', ['shop_id'])
    op.create_index('ix_shop_clients_client_id', 'shop_clients', ['client_id'])

    op.create_table(
        'shop_cars',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('shop_id', sa.Integer(), nullable=False),
        sa.Column('local_id', sa.Integer(), nullable=False),
        sa.Column('car_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id']),
        sa.ForeignKeyConstraint(['car_id'], ['cars.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shop_id', 'local_id', name='uq_shop_cars_local'),
    )
    op.create_index('ix_shop_cars_shop_id', 'shop_cars', ['shop_id'])
    op.create_index('ix_shop_cars_car_id', 'shop_cars', ['car_id'])

    # QR телефона: какой код уже использован — в базе, а не в памяти
    with op.batch_alter_table('master_devices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('link_sig', sa.String(length=32), nullable=True))
        batch_op.create_unique_constraint('uq_master_devices_link_sig', ['link_sig'])

    # Перенос: связь — к первой точке аккаунта
    op.execute("""
        INSERT INTO shop_clients (shop_id, local_id, client_id)
        SELECT (SELECT MIN(s.id) FROM shops s WHERE s.account_id = c.account_id),
               c.local_id, c.id
        FROM clients c
        WHERE c.local_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM shops s WHERE s.account_id = c.account_id)
    """)
    op.execute("""
        INSERT INTO shop_cars (shop_id, local_id, car_id)
        SELECT (SELECT MIN(s.id) FROM shops s WHERE s.account_id = c.account_id),
               c.local_id, c.id
        FROM cars c
        WHERE c.local_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM shops s WHERE s.account_id = c.account_id)
    """)


def downgrade() -> None:
    with op.batch_alter_table('master_devices', schema=None) as batch_op:
        batch_op.drop_constraint('uq_master_devices_link_sig', type_='unique')
        batch_op.drop_column('link_sig')
    op.drop_index('ix_shop_cars_car_id', table_name='shop_cars')
    op.drop_index('ix_shop_cars_shop_id', table_name='shop_cars')
    op.drop_table('shop_cars')
    op.drop_index('ix_shop_clients_client_id', table_name='shop_clients')
    op.drop_index('ix_shop_clients_shop_id', table_name='shop_clients')
    op.drop_table('shop_clients')
