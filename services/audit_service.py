"""
Журнал действий с деньгами и настройками.

Отвечает на вопросы «кто удалил наряд», «когда подняли цену»,
«кто менял ставку зарплаты». Раньше следов не оставалось вовсе.
"""
from models import AuditLog
from logger import log


class AuditService:
    # Коды действий — чтобы записи можно было отбирать и понимать
    ORDER_DELETE = 'order.delete'
    ORDER_HARD_DELETE = 'order.hard_delete'
    PRICE_CHANGE = 'price.change'
    STORAGE_PRICE_CHANGE = 'price.storage_change'
    SALARY_PERCENT_CHANGE = 'employee.salary_percent'
    STORAGE_RELEASE = 'storage.release'
    SALARY_PAYOUT = 'salary.payout'
    SALARY_PAYOUT_CANCEL = 'salary.payout_cancel'
    PIN_FAILED = 'auth.pin_failed'
    PIN_CHANGED = 'auth.pin_changed'

    # Как показывать код действия человеку
    TITLES = {
        ORDER_DELETE: 'Удаление наряда',
        ORDER_HARD_DELETE: 'Удаление черновика',
        PRICE_CHANGE: 'Изменение цены',
        STORAGE_PRICE_CHANGE: 'Изменение цены хранения',
        SALARY_PERCENT_CHANGE: 'Изменение ставки ЗП',
        STORAGE_RELEASE: 'Выдача шин',
        SALARY_PAYOUT: 'Выдача зарплаты',
        SALARY_PAYOUT_CANCEL: 'Отмена выдачи зарплаты',
        PIN_FAILED: 'Неверный PIN-код',
        PIN_CHANGED: 'Смена PIN-кода',
    }

    def __init__(self, db):
        self.db = db

    def log(self, action, description, entity_type=None, entity_id=None,
            employee_id=None, commit=True):
        """
        Записать действие в журнал.

        Сбой записи в журнал не должен ломать саму операцию: если наряд
        удалён, а журнал не записался, важнее сохранить удаление.
        """
        try:
            entry = AuditLog(
                action=action,
                description=description,
                entity_type=entity_type,
                entity_id=entity_id,
                employee_id=employee_id,
            )
            self.db.add(entry)
            if commit:
                self.db.commit()
            return entry
        except Exception as e:
            log.error(f"Не удалось записать действие в журнал: {e}")
            return None

    def get_recent(self, limit=200, action=None):
        """Последние записи журнала, свежие сверху."""
        query = self.db.query(AuditLog)
        if action:
            query = query.filter(AuditLog.action == action)
        return query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).all()

    @classmethod
    def title(cls, action):
        return cls.TITLES.get(action, action)
