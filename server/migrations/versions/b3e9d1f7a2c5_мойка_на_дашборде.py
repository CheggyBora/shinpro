"""Мойка на дашборде

Наряд бывает смешанным: в нём и шиномонтаж, и мойка. Дашборд мойки
делит такой наряд по строкам (docs/wash_dashboard.md), поэтому
направление теперь есть у самого наряда, у каждой его позиции и у
каждого начисления. У позиции мойки ещё и мойщик: мойку делает один
человек, а не «все мастера наряда».

Всё, что лежало до этого шага, — шиномонтаж: мойки на дашборде тогда
не было, поэтому старые строки получают «tire» прямо в базе.

Revision ID: b3e9d1f7a2c5
Revises: a6f2c8e4b1d7
Create Date: 2026-10-26 23:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3e9d1f7a2c5'
down_revision: Union[str, Sequence[str], None] = 'a6f2c8e4b1d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('visits', schema=None) as batch_op:
        batch_op.add_column(sa.Column('directions', sa.String(length=20),
                                      nullable=False, server_default='tire'))
        batch_op.add_column(sa.Column('wash_class', sa.String(length=16),
                                      nullable=True))

    with op.batch_alter_table('visit_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('direction', sa.String(length=10),
                                      nullable=False, server_default='tire'))
        batch_op.add_column(sa.Column('employee_local_id', sa.Integer(),
                                      nullable=True))

    with op.batch_alter_table('salary_accruals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('direction', sa.String(length=10),
                                      nullable=False, server_default='tire'))


def downgrade() -> None:
    with op.batch_alter_table('salary_accruals', schema=None) as batch_op:
        batch_op.drop_column('direction')

    with op.batch_alter_table('visit_items', schema=None) as batch_op:
        batch_op.drop_column('employee_local_id')
        batch_op.drop_column('direction')

    with op.batch_alter_table('visits', schema=None) as batch_op:
        batch_op.drop_column('wash_class')
        batch_op.drop_column('directions')
