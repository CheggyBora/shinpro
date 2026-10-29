"""Доступ: свои галочки календаря, склада и кассы; Telegram и отчёты у людей

Раньше календарь и склад видел всякий, кто вошёл в дашборд, а касса шла
вместе с выручкой. Теперь у каждого раздела своя галочка — а у тех, кому
права заданы вручную, ничего не пропадает: календарь и склад остаются,
касса — у тех, кто видел выручку.

Владелец сервера отмечается флагом, а не номером из настроек: номер
можно сменить в дашборде (решение владельца 29.10.2026).

Revision ID: f4b8d2a6c1e9
Revises: e9a1c3f5b7d2
Create Date: 2026-10-29 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f4b8d2a6c1e9'
down_revision: Union[str, Sequence[str], None] = 'e9a1c3f5b7d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('staff_users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_platform_owner', sa.Boolean(), nullable=False,
                                      server_default='0'))
        batch_op.add_column(sa.Column('telegram', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('reports', sa.Text(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, permissions FROM staff_users WHERE permissions IS NOT NULL")).fetchall()
    for staff_id, permissions in rows:
        chosen = [p.strip() for p in (permissions or '').split(',') if p.strip()]
        for extra in ('calendar', 'stock'):
            if extra not in chosen:
                chosen.append(extra)
        if 'revenue' in chosen and 'cash' not in chosen:
            chosen.append('cash')
        bind.execute(sa.text("UPDATE staff_users SET permissions = :p WHERE id = :i"),
                     {'p': ','.join(chosen), 'i': staff_id})


def downgrade() -> None:
    with op.batch_alter_table('staff_users', schema=None) as batch_op:
        batch_op.drop_column('reports')
        batch_op.drop_column('telegram')
        batch_op.drop_column('is_platform_owner')
