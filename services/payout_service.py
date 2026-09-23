"""
Выдача зарплаты.

Начисление и выдача — разные события, и путать их нельзя. Начисление
появляется само, когда наряд оплачен. Выдача — когда деньги отдали
человеку в руки или перевели на карту. Остаток к выдаче это разница,
и считается он от начала работы, а не за период: иначе прошлый
невыданный хвост просто потеряется при смене месяца.

Выдать может только тот, кто знает админский PIN: деньги уходят из
кассы, и след о том, кто их выдал, должен остаться.

Выплату на карту может отметить владелец из дашборда. Такая выдача
приходит в цех при обмене — со своим номером на сервере, чтобы
повторная присылка не создала вторую запись.
"""
from sqlalchemy import func

from models import SalaryTransaction


class PayoutError(Exception):
    """Понятная человеку причина, почему выдать не вышло."""


class PayoutService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Сколько человеку причитается
    # ------------------------------------------------------------------

    def accrued(self, employee_id, since=None, until=None):
        """Начислено по нарядам. Удалённые наряды не в счёт."""
        from models import WorkOrder

        query = self.db.query(func.sum(SalaryTransaction.amount)).join(
            WorkOrder, SalaryTransaction.work_order_id == WorkOrder.id
        ).filter(
            SalaryTransaction.employee_id == employee_id,
            WorkOrder.is_deleted.is_(False))

        if since is not None:
            query = query.filter(SalaryTransaction.transaction_date >= since)
        if until is not None:
            query = query.filter(SalaryTransaction.transaction_date <= until)

        return round(float(query.scalar() or 0.0), 2)

    def paid(self, employee_id, since=None, until=None):
        """Сколько уже выдано на руки."""
        from models import SalaryPayout

        query = self.db.query(func.sum(SalaryPayout.amount)).filter(
            SalaryPayout.employee_id == employee_id)

        if since is not None:
            query = query.filter(SalaryPayout.paid_at >= since)
        if until is not None:
            query = query.filter(SalaryPayout.paid_at <= until)

        return round(float(query.scalar() or 0.0), 2)

    def balance(self, employee_id):
        """
        Остаток к выдаче: начислено за всё время минус выданное.

        Отрицательный остаток — долг сотрудника: ему выдали вперёд.
        """
        return round(self.accrued(employee_id) - self.paid(employee_id), 2)

    def summary(self, employee_id):
        accrued = self.accrued(employee_id)
        paid = self.paid(employee_id)
        return {
            'employee_id': employee_id,
            'accrued': accrued,
            'paid': paid,
            'balance': round(accrued - paid, 2),
        }

    def everyone(self, only_active=True):
        """Остатки по всем сотрудникам — для экрана выдачи и ведомости."""
        from models import Employee

        query = self.db.query(Employee)
        if only_active:
            query = query.filter(Employee.is_active.is_(True))

        rows = []
        for employee in query.order_by(Employee.id).all():
            row = self.summary(employee.id)
            row['employee'] = employee
            row['title'] = employee.title
            rows.append(row)
        return rows

    # ------------------------------------------------------------------
    # Сама выдача
    # ------------------------------------------------------------------

    def pay(self, employee_id, amount, method, pin=None, comment=None,
            allow_advance=False, source='shop', server_id=None):
        """
        Выдать зарплату. Возвращает запись о выдаче.

        Сумму больше остатка принимаем только с allow_advance: это аванс,
        и человек должен подтвердить, что понимает это. Молча выдавать
        вперёд нельзя — через месяц никто не вспомнит, почему остаток
        отрицательный.
        """
        from models import Employee, SalaryPayout, METHOD_CASH, METHOD_CARD
        from services.auth_service import AuthService
        from services.audit_service import AuditService

        employee = self.db.query(Employee).filter(
            Employee.id == employee_id).first()
        if employee is None:
            raise PayoutError(f"Сотрудник №{employee_id} не найден")

        try:
            amount = round(float(amount), 2)
        except (TypeError, ValueError):
            raise PayoutError("Сумма выдачи должна быть числом")

        if amount <= 0:
            raise PayoutError("Сумма выдачи должна быть больше нуля")

        if method not in (METHOD_CASH, METHOD_CARD):
            raise PayoutError(f"Неизвестный способ выплаты: {method}")

        # Выплату из дашборда PIN-кодом подтверждать не у кого: её уже
        # подтвердил владелец, войдя в дашборд под своим ПИНом
        if source == 'shop':
            if not AuthService(self.db).verify_pin(pin):
                AuditService(self.db).log(
                    AuditService.PIN_FAILED,
                    f"Неверный PIN при выдаче зарплаты: {employee.title}")
                raise PayoutError("Неверный PIN-код")

        balance = self.balance(employee_id)
        is_advance = amount > balance + 0.009

        if is_advance and not allow_advance:
            # Разряды разделяем сами: пробел вместо запятой, иначе
            # запятая из формата съедает знаки препинания в тексте
            left = f"{balance:,.0f}".replace(',', ' ')
            asked = f"{amount:,.0f}".replace(',', ' ')
            raise PayoutError(
                f"К выдаче {left} руб., а выдаётся {asked}. "
                f"Это аванс — подтвердите отдельно")

        payout = SalaryPayout(
            employee_id=employee_id,
            amount=amount,
            method=method,
            comment=(comment or '').strip() or None,
            is_advance=is_advance,
            source=source,
            server_id=server_id)
        self.db.add(payout)
        self.db.commit()
        self.db.refresh(payout)

        way = 'наличными' if method == METHOD_CASH else 'на карту'
        AuditService(self.db).log(
            AuditService.SALARY_PAYOUT,
            f"Выдана зарплата {employee.title}: {amount:.2f} руб. {way}"
            + (', аванс' if is_advance else '')
            + (', отметил владелец в дашборде' if source == 'dashboard' else ''),
            entity_type='salary_payout',
            entity_id=payout.id,
            employee_id=employee_id)

        return payout

    def cancel(self, payout_id, pin):
        """
        Отменить выдачу — если ошиблись суммой или сотрудником.

        Запись удаляем, а не помечаем: выдачи не было, и в ведомости ей
        взяться неоткуда. След остаётся в журнале действий.
        """
        from models import SalaryPayout
        from services.auth_service import AuthService
        from services.audit_service import AuditService

        if not AuthService(self.db).verify_pin(pin):
            raise PayoutError("Неверный PIN-код")

        payout = self.db.query(SalaryPayout).filter(
            SalaryPayout.id == payout_id).first()
        if payout is None:
            raise PayoutError("Выдача не найдена")

        amount, employee_id = payout.amount, payout.employee_id
        self.db.delete(payout)
        self.db.commit()

        AuditService(self.db).log(
            AuditService.SALARY_PAYOUT_CANCEL,
            f"Отменена выдача №{payout_id}: {amount:.2f} руб.",
            entity_type='salary_payout',
            entity_id=payout_id,
            employee_id=employee_id)

        return True

    # ------------------------------------------------------------------
    # История и ведомость
    # ------------------------------------------------------------------

    def history(self, employee_id=None, since=None, until=None, limit=500):
        from models import SalaryPayout

        query = self.db.query(SalaryPayout)
        if employee_id is not None:
            query = query.filter(SalaryPayout.employee_id == employee_id)
        if since is not None:
            query = query.filter(SalaryPayout.paid_at >= since)
        if until is not None:
            query = query.filter(SalaryPayout.paid_at <= until)

        return query.order_by(SalaryPayout.paid_at.desc()).limit(limit).all()

    def statement(self, since, until):
        """
        Ведомость за период: по каждому сотруднику начислено и выдано.

        Начислено берём за период, остаток — за всё время: в ведомости
        нужны обе цифры. «Начислено в марте» отвечает на вопрос, сколько
        человек заработал, а остаток — сколько ему ещё должны.
        """
        from models import Employee, METHOD_CASH, METHOD_CARD

        rows = []
        for employee in self.db.query(Employee).order_by(Employee.id).all():
            accrued = self.accrued(employee.id, since, until)
            payouts = self.history(employee.id, since, until)
            paid = round(sum(item.amount for item in payouts), 2)

            if not accrued and not paid:
                continue

            rows.append({
                'employee_id': employee.id,
                'title': employee.title,
                'accrued': accrued,
                'paid': paid,
                'cash': round(sum(item.amount for item in payouts
                                  if item.method == METHOD_CASH), 2),
                'card': round(sum(item.amount for item in payouts
                                  if item.method == METHOD_CARD), 2),
                'balance': self.balance(employee.id),
                'payouts': payouts,
            })

        return rows
