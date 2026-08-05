"""
Alembic environment — настройка подключения к БД + autogenerate.

Что важно:
- Читает DATABASE_URL из .env (не из alembic.ini)
- Знает про наши модели → autogenerate работает
"""
import os
import sys
from pathlib import Path
from logging.config import fileConfig

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent),
)

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from execution.database.models import Base
from execution.models.reviews import Review  # noqa: F401
# Загружаем .env
load_dotenv()


# --- Импорт наших моделей ---
# Base.metadata знает про все таблицы → alembic сможет их создавать


target_metadata = Base.metadata


# --- Стандартный alembic config ---

config = context.config

# Подставляем DATABASE_URL из .env
database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL не найден в .env")
config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    """Генерация SQL без реального подключения (пишет .sql файл)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Обычный режим — подключаемся к БД и применяем миграции."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()