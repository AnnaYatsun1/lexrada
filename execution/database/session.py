# from chromadb.app import settings
# from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession




# engine = create_async_engine(
#     settings.DATABASE_URL,
#     echo=True
# )

# SessionLocal = async_sessionmaker(
#     engine,
#     class_= AsyncSession,
#     expire_on_commit=False
# )

"""
Подключение к PostgreSQL через SQLAlchemy.

Использование:
    from execution.database.session import get_session
    
    with get_session() as session:
        user = session.get(User, 1)
        session.commit()
"""
import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session


# Читаем URL из .env
# Формат: postgresql://user:password@host:port/dbname
from dotenv import load_dotenv

load_dotenv() 
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL не найден в .env. "
        "Добавь: DATABASE_URL=postgresql://lexradar:lexradar_dev_password@db:5432/lexradar"
    )


# Engine — "соединение с БД" на уровне драйвера.
# Один на всё приложение, создаётся при импорте.
engine = create_engine(
    DATABASE_URL,
    echo=False,          # True → печатает каждый SQL в консоль (полезно для debug, шумно в prod)
    pool_pre_ping=True,  # проверяет "живо ли соединение" перед использованием
    pool_size=5,         # максимум 5 одновременных соединений
    max_overflow=10,     # ещё 10 если понадобится всплеск
)


# SessionLocal — "фабрика сессий". Каждая сессия = одна логическая транзакция.
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,        # не отправлять изменения в БД автоматически
    autocommit=False,       # не коммитить автоматически
    expire_on_commit=False, # объекты остаются "живыми" после commit
)


@contextmanager
def get_session():
    """
    Контекстный менеджер для работы с БД.
    
    Автоматически:
    - открывает сессию
    - закрывает при выходе
    - откатывает если было исключение
    
    Пример:
        with get_session() as session:
            user = session.get(User, 1)
            session.commit()
    """
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()