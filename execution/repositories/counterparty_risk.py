from execution.repositories.base import BaseRepository


"""Репозиторий для рисков контрагентов."""
from datetime import datetime, UTC
from enum import Enum

from sqlalchemy import select

from execution.repositories.base import BaseRepository
from execution.database.models import CounterpartyRisk


class RiskSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CounterpartyRiskRepository(BaseRepository[CounterpartyRisk]):
    model = CounterpartyRisk

    def record(
        self,
        user_id: int,
        counterparty_inn: str,
        processing_id: int,
        document_number: str | None,
        risk_text: str,
        severity: RiskSeverity | str = RiskSeverity.MEDIUM,
    ) -> CounterpartyRisk:
        """Сохранить обнаруженный риск по контрагенту."""
        severity_value = severity.value if isinstance(severity, RiskSeverity) else severity

        risk = CounterpartyRisk(
            user_id=user_id,
            counterparty_inn=counterparty_inn,
            processing_id=processing_id,
            document_number=document_number,
            risk_text=risk_text,
            severity=severity_value,
            found_at=datetime.now(UTC),
        )
        self.add(risk)
        return risk

    def list_by_counterparty(
        self,
        user_id: int,
        inn: str,
        limit: int = 10,
    ) -> list[CounterpartyRisk]:
        """История рисков конкретного контрагента у конкретного юзера. Свежие первыми."""
        stmt = (
            select(CounterpartyRisk)
            .where(
                CounterpartyRisk.user_id == user_id,
                CounterpartyRisk.counterparty_inn == inn,
            )
            .order_by(CounterpartyRisk.found_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())