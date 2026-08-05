
from execution.database.models import User
from sqlalchemy import select
from datetime import datetime, UTC
from execution.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    def get_by_api_key(self, api_key: str) -> User | None:
        """
        Найти юзера по API-ключу. Используется в auth (X-API-Key).
        Возвращает User или None если ключ невалиден.
        """
        stmt = select(self.model).where(self.model.api_key == api_key)
        return self.session.scalar(stmt)
    def get_by_telegram_chat_id(self, telegram_chat_id: str) -> User | None:
        return (
            self.session.query(User)
            .filter(User.telegram_chat_id == telegram_chat_id)
            .first()
        )
    
    def get_by_email(self, email: str) -> User | None:
        """Найти юзера по email."""
        stmt = select(self.model).where(self.model.email == email)
        return self.session.scalar(stmt)

    def create(
        self,
        api_key: str,
        email: str | None = None,
        name: str | None = None,
        telegram_chat_id: str | None = None,
        telegram_username: str | None = None,
        preferred_delivery: str = "telegram",
    ) -> User:
        """Создать нового юзера. Не коммитит — вызывающий делает commit."""
        user = User(
            api_key=api_key,
            email=email,
            name=name,
            telegram_chat_id=telegram_chat_id,
            telegram_username=telegram_username,
            preferred_delivery=preferred_delivery,
            created_at=datetime.now(UTC),
        )
        self.add(user)
        self.session.flush()
        return user