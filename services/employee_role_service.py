"""
Категории сотрудников и услуги, с которых им не начисляется.

Список задаётся на категорию, а не на человека: пришёл новый съёмщик —
поставили ему категорию, и всё уже настроено.

Правки действуют на будущие оплаты. Уже начисленное не пересчитывается:
разбор каждого начисления сохранён вместе с ним.
"""
from sqlalchemy.orm import Session

from models import Employee, EmployeeRole, Service

# Категории по умолчанию заводятся один раз. Без отметки удалённые
# владельцем возвращались бы при каждом запуске
SEEDED_KEY = 'employee_roles_seeded'

# Исключений по умолчанию нет ни у кого: какие услуги считать «только
# для мастеров», решает владелец. Пока он не отметил, считается как
# раньше — со всего.
# (название, может ли стоять на смене один)
DEFAULT_ROLES = [('Мастер', True), ('Сезонный мастер', True),
                 ('Сезонный съёмщик', False)]


class EmployeeRoleService:
    def __init__(self, db: Session):
        self.db = db

    def ensure_defaults(self):
        from services.settings_service import SettingsService

        settings = SettingsService(self.db)
        if settings.get(SEEDED_KEY) == '1':
            return
        if not self.db.query(EmployeeRole).count():
            for title, alone in DEFAULT_ROLES:
                self.db.add(EmployeeRole(title=title, can_work_alone=alone))
        settings.set(SEEDED_KEY, '1', commit=False)
        self.db.commit()

    # ------------------------------------------------------------------
    # Категории
    # ------------------------------------------------------------------

    ADMIN_SEEDED_KEY = 'employee_role_admin_seeded'
    ADMIN_TITLE = 'Администратор'

    def ensure_admin(self):
        """
        Категория «Администратор» — один раз. Удалили или сняли отметку —
        не возвращаем: значит, у владельца администратора нет.
        """
        from services.settings_service import SettingsService
        settings = SettingsService(self.db)
        if settings.get(self.ADMIN_SEEDED_KEY) == '1':
            return
        if not self.db.query(EmployeeRole).filter(EmployeeRole.is_admin.is_(True)).first():
            same = self.db.query(EmployeeRole).filter(
                EmployeeRole.title == self.ADMIN_TITLE).first()
            if same is not None:
                same.is_admin = True
            else:
                self.db.add(EmployeeRole(title=self.ADMIN_TITLE, can_work_alone=True,
                                         is_admin=True))
        settings.set(self.ADMIN_SEEDED_KEY, '1', commit=False)
        self.db.commit()

    def admin_role(self):
        """Категория администратора. Её удалили — заводим заново: человека
        отметили администратором при создании, значит, она нужна."""
        self.roles()
        role = self.db.query(EmployeeRole).filter(EmployeeRole.is_admin.is_(True)).order_by(
            EmployeeRole.id).first()
        if role is None:
            role = self.db.query(EmployeeRole).filter(EmployeeRole.title == self.ADMIN_TITLE).first()
            if role is None:
                role = EmployeeRole(title=self.ADMIN_TITLE, can_work_alone=True)
                self.db.add(role)
            role.is_admin = True
            self.db.commit()
        return role

    def roles(self):
        self.ensure_defaults()
        self.ensure_admin()
        return self.db.query(EmployeeRole).order_by(EmployeeRole.id).all()

    def get(self, role_id):
        if role_id is None:
            return None
        return self.db.query(EmployeeRole).filter(
            EmployeeRole.id == role_id).first()

    def _clean_title(self, title, skip_id=None):
        title = (title or '').strip()
        if not title:
            raise ValueError('Укажите название категории')
        same = self.db.query(EmployeeRole).filter(EmployeeRole.title == title)
        if skip_id is not None:
            same = same.filter(EmployeeRole.id != skip_id)
        if same.first():
            raise ValueError(f'Категория «{title}» уже есть')
        return title

    def add(self, title):
        self.ensure_defaults()
        role = EmployeeRole(title=self._clean_title(title))
        self.db.add(role)
        self.db.commit()
        return role

    def rename(self, role_id, title):
        role = self.get(role_id)
        if role is None:
            raise ValueError('Категория не найдена')
        role.title = self._clean_title(title, skip_id=role_id)
        self.db.commit()
        return role

    def count_employees(self, role_id):
        return self.db.query(Employee).filter(
            Employee.role_id == role_id).count()

    def delete(self, role_id):
        """Удалить категорию. Её сотрудники становятся обычными мастерами."""
        role = self.get(role_id)
        if role is None:
            return 0
        moved = self.db.query(Employee).filter(
            Employee.role_id == role_id).update(
                {Employee.role_id: None}, synchronize_session=False)
        self.db.delete(role)
        self.db.commit()
        return moved

    def set_excluded(self, role_id, names):
        role = self.get(role_id)
        if role is None:
            raise ValueError('Категория не найдена')
        before = role.excluded
        role.set_excluded(names)
        self.db.commit()

        # Это правка того, сколько людям начисляется, — в журнал
        after = role.excluded
        added, removed = sorted(after - before), sorted(before - after)
        if added or removed:
            from services.audit_service import AuditService
            parts = []
            if added:
                parts.append('не начислять: ' + ', '.join(added))
            if removed:
                parts.append('снова начислять: ' + ', '.join(removed))
            AuditService(self.db).log(
                'employee_role.services',
                f"Категория «{role.title}»: " + '; '.join(parts),
                entity_type='employee_role', entity_id=role.id)
        return role

    def set_can_work_alone(self, role_id, value):
        role = self.get(role_id)
        if role is None:
            raise ValueError('Категория не найдена')
        role.can_work_alone = bool(value)
        self.db.commit()
        return role

    def set_admin(self, role_id, value):
        role = self.get(role_id)
        if role is None:
            raise ValueError('Категория не найдена')
        role.is_admin = bool(value)
        self.db.commit()
        return role

    def is_admin(self, employee):
        role = self.role_of(employee)
        return bool(role is not None and role.is_admin)

    def can_work_alone(self, employee):
        """Без категории — обычный мастер: может."""
        role = self.role_of(employee)
        return True if role is None else role.can_work_alone is not False

    def service_names(self, direction=None):
        """
        Услуги, которые можно исключить: работы из прайса, без товаров.
        По названию — одна строка на «Правку» для всех типов машин.
        direction — только этого направления ('tire', 'wash').
        """
        query = self.db.query(Service.name).filter(
            Service.is_active.isnot(False),
            Service.is_goods.isnot(True))
        if direction == 'tire':
            query = query.filter((Service.direction == 'tire') | Service.direction.is_(None))
        elif direction:
            query = query.filter(Service.direction == direction)
        return sorted({name for (name,) in query.distinct().all() if name})

    def set_goods(self, role_id, directions_list):
        """Администратору — с товаров каких направлений платить."""
        role = self.get(role_id)
        if role is None:
            raise ValueError('Категория не найдена')
        chosen = [d for d in ('tire', 'wash') if d in set(directions_list)]
        before = role.goods_from
        role.goods_directions = ','.join(chosen) or None
        self.db.commit()
        if set(chosen) != before:
            from services.audit_service import AuditService
            titles = {'tire': 'шиномонтажа', 'wash': 'мойки'}
            AuditService(self.db).log(
                'employee_role.goods',
                f"Категория «{role.title}»: с товаров — " +
                (', '.join(titles[d] for d in chosen) if chosen else 'не платить'),
                entity_type='employee_role', entity_id=role.id)
        return role

    # ------------------------------------------------------------------
    # Сотрудник
    # ------------------------------------------------------------------

    def role_of(self, employee):
        if employee is None or employee.role_id is None:
            return None
        return self.get(employee.role_id)

    def set_employee_role(self, employee_id, role_id):
        employee = self.db.query(Employee).filter(
            Employee.id == employee_id).first()
        if employee is None:
            raise ValueError(f'Сотрудник №{employee_id} не найден')
        if role_id is not None and self.get(role_id) is None:
            raise ValueError('Такой категории уже нет')
        employee.role_id = role_id
        self.db.commit()
        return employee

    def role_title(self, employee):
        role = self.role_of(employee)
        return role.title if role else 'Мастер'
