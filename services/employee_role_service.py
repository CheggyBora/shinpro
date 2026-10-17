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
# раньше — со всего
DEFAULT_ROLES = ['Мастер', 'Сезонный мастер', 'Сезонный съёмщик']


class EmployeeRoleService:
    def __init__(self, db: Session):
        self.db = db

    def ensure_defaults(self):
        from services.settings_service import SettingsService

        settings = SettingsService(self.db)
        if settings.get(SEEDED_KEY) == '1':
            return
        if not self.db.query(EmployeeRole).count():
            for title in DEFAULT_ROLES:
                self.db.add(EmployeeRole(title=title))
        settings.set(SEEDED_KEY, '1', commit=False)
        self.db.commit()

    # ------------------------------------------------------------------
    # Категории
    # ------------------------------------------------------------------

    def roles(self):
        self.ensure_defaults()
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

    def service_names(self):
        """
        Услуги, которые можно исключить: работы из прайса, без товаров.
        По названию — одна строка на «Правку» для всех типов машин.
        """
        rows = self.db.query(Service.name).filter(
            Service.is_active.isnot(False),
            Service.is_goods.isnot(True)).distinct().all()
        return sorted({name for (name,) in rows if name})

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
