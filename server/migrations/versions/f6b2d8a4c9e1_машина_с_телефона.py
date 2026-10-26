"""Машина с телефона

Наряд по фото машины (docs/order_photo.md). Телефон снимает машину при
приезде, сервер распознаёт номер, цех забирает «машину с телефона» и
создаёт по ней наряд — снимок становится обложкой наряда.

У снимка появляется вид: photo — от мастера для клиента, cover —
обложка. Всё, что лежало до этого шага, — снимки мастеров.

Revision ID: f6b2d8a4c9e1
Revises: d4a8c2e6f1b9
Create Date: 2026-10-27 00:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6b2d8a4c9e1'
down_revision: Union[str, Sequence[str], None] = 'd4a8c2e6f1b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('order_photos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String(length=10),
                                      nullable=False, server_default='photo'))

    op.create_table(
        'arrivals',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('shop_id', sa.Integer(), nullable=False),
        sa.Column('photo_id', sa.Integer(), nullable=True),
        sa.Column('plate', sa.String(length=20), nullable=False,
                  server_default=''),
        sa.Column('directions', sa.String(length=20), nullable=False,
                  server_default='tire'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('done_at', sa.DateTime(), nullable=True),
        sa.Column('order_local_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id']),
        sa.ForeignKeyConstraint(['photo_id'], ['order_photos.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('arrivals', schema=None) as batch_op:
        batch_op.create_index('ix_arrivals_shop_id', ['shop_id'], unique=False)
        batch_op.create_index('ix_arrivals_created_at', ['created_at'],
                              unique=False)


def downgrade() -> None:
    with op.batch_alter_table('arrivals', schema=None) as batch_op:
        batch_op.drop_index('ix_arrivals_created_at')
        batch_op.drop_index('ix_arrivals_shop_id')
    op.drop_table('arrivals')

    with op.batch_alter_table('order_photos', schema=None) as batch_op:
        batch_op.drop_column('kind')
