"""Календарь: комментарии, время «до», Telegram контрагента

Запись календаря теперь двух видов: задача (с галочкой, напоминает,
переходит на завтра) и комментарий — просто запись на день. Всё, что
было до этого шага, — задачи. У записи появилось время окончания
(решение владельца 29.10.2026).

Revision ID: d2e7a9c4b6f1
Revises: b4d6f8a2c1e3
Create Date: 2026-10-29 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd2e7a9c4b6f1'
down_revision: Union[str, Sequence[str], None] = 'b4d6f8a2c1e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String(length=10), nullable=False,
                                      server_default='task'))
        batch_op.add_column(sa.Column('end_time', sa.String(length=5), nullable=True))
    # Ник контрагента в Telegram: задача с ним уходит ему лично
    with op.batch_alter_table('counterparties', schema=None) as batch_op:
        batch_op.add_column(sa.Column('telegram', sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('counterparties', schema=None) as batch_op:
        batch_op.drop_column('telegram')
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_column('end_time')
        batch_op.drop_column('kind')
