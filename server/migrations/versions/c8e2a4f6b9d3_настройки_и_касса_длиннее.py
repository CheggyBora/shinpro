"""Настройки точки и причина расхождения кассы — не короче, чем в цеху

В цеху значение настройки до 500 знаков (реквизиты, кому какие отчёты),
на сервере было 255; причина расхождения кассы — 300 против 255.
Длинное значение роняло весь обмен точки, как номер машины (30.10.2026).

Revision ID: c8e2a4f6b9d3
Revises: b5d9f3a7c1e4
Create Date: 2026-10-30 22:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8e2a4f6b9d3'
down_revision: Union[str, Sequence[str], None] = 'b5d9f3a7c1e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('shop_settings', schema=None) as batch_op:
        batch_op.alter_column('value', existing_type=sa.String(255), type_=sa.Text(),
                              existing_nullable=True)
    with op.batch_alter_table('shop_shifts', schema=None) as batch_op:
        batch_op.alter_column('cash_diff_reason', existing_type=sa.String(255),
                              type_=sa.String(300), existing_nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('shop_shifts', schema=None) as batch_op:
        batch_op.alter_column('cash_diff_reason', existing_type=sa.String(300),
                              type_=sa.String(255), existing_nullable=True)
    with op.batch_alter_table('shop_settings', schema=None) as batch_op:
        batch_op.alter_column('value', existing_type=sa.Text(), type_=sa.String(255),
                              existing_nullable=True)
