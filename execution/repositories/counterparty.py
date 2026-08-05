

from execution.repositories.base import BaseRepository


"""Репозиторий для контрагентов (Counterparty)."""
from datetime import datetime, UTC

from sqlalchemy import select

from execution.repositories.base import BaseRepository
from execution.database.models import Counterparty


class CounterpartyRepository(BaseRepository[Counterparty]):
    model = Counterparty

    def get(self, user_id: int, inn: str) -> Counterparty | None:
        """
        Найти контрагента по составному ключу (user_id, inn).
        Используем session.get с tuple — SQLAlchemy знает про composite PK.
        """
        return self.session.get(Counterparty, (user_id, inn))

    def save_or_update(self, user_id: int, inn: str, name: str) -> Counterparty:
        """
        Upsert контрагента:
        - Если есть → увеличиваем times_seen, обновляем last_seen
        - Если нет → создаём с times_seen=1

        Возвращает обновлённый или созданный объект.
        """
        now = datetime.now(UTC)
        counterparty = self.get(user_id, inn)

        if counterparty:
            counterparty.times_seen += 1
            counterparty.last_seen = now
        else:
            counterparty = Counterparty(
                user_id=user_id,
                inn=inn,
                name=name,
                times_seen=1,
                first_seen=now,
                last_seen=now,
            )
            self.add(counterparty)
            self.session.flush()

        return counterparty

    def list_by_user(self, user_id: int, limit: int = 100, offset: int = 0) -> list[Counterparty]:
        """Все контрагенты юзера — для дашборда или API."""
        stmt = (
            select(Counterparty)
            .where(Counterparty.user_id == user_id)
            .order_by(Counterparty.last_seen.desc())
            .limit(limit)
            .offset(offset)
        )