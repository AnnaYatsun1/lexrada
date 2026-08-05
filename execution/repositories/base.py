"""
Базовый репозиторий для всех сущностей БД.

Даёт стандартные CRUD-операции которые одинаковы для всех таблиц:
- get_by_id
- list_all
- delete_by_id
- count

Специфичные методы живут в наследниках.
"""
from typing import Generic, TypeVar, Type
from sqlalchemy import select, delete, func
from sqlalchemy.orm import Session

from execution.database.models import Base
T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    model: Type[T]
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_by_id(self, entity_id) -> T | None:
        """
        Получить запись по primary key.
        Возвращает объект модели или None если не найдено.
        """
        return self.session.get(self.model, entity_id)
    
    def list_all(self, limit: int = 100, offset: int = 0) -> list[T]:
        """Получить все записи (осторожно на больших таблицах!)."""
        stmt = select(self.model).limit(limit).offset(offset)
        return list(self.session.scalars(stmt).all())
    
    def count(self) -> int:
        """Посчитать общее количество записей."""
        stmt = select(func.count()).select_from(self.model)
        return self.session.scalar(stmt) or 0
    
    def delete_by_id(self, entity_id) -> bool:
        """
        Удалить запись по id. Возвращает True если удалено, False если не найдено.
        """
        entity = self.get_by_id(entity_id)
        if entity is None:
            return False
        self.session.delete(entity)
        return True
    
    def add(self, entity: T) -> T:
        """Добавить новую запись в сессию (без commit)."""
        self.session.add(entity)
        return entity
    
    def flush(self):
        """Отправить изменения в БД без commit (например, чтобы получить сгенерированный id)."""
        self.session.flush()

    def refresh(self, entity: T) -> T:
        """Перечитать объект из БД (актуализировать поля)."""
        self.session.refresh(entity)
        return entity
    
    def exists(self, entity_id: int) -> bool:
        if entity_id == None:
            return False
        return self.get_by_id(entity_id) is not None