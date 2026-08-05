"""
Скрипт переноса данных из старого SQLite в новый Postgres.

Запуск из корня проекта:
    python3 -m scripts.migrations.sqlite_to_postgres

ВАЖНО:
- Использует существующий data/processings.db (SQLite)
- Пишет в Postgres из DATABASE_URL в .env
- Не удаляет SQLite — оставляем как бэкап
- Идемпотентный: повторный запуск проверяет что уже перенесено
"""
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

# позволяет запускать из корня
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text, select, func

from paths import DB_PATH  # SQLite path из paths.py
from execution.database.session import SessionLocal
from execution.database.models import (
    User, Processing, LLMCall, Counterparty, CounterpartyRisk
)


def parse_dt(value):
    """SQLite хранит даты как строки → конвертируем в datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if "T" in value else datetime.fromisoformat(value)


def migrate():
    print(f"📂 SQLite: {DB_PATH}")
    print(f"🎯 Postgres: (из DATABASE_URL)\n")

    # Подключаемся к SQLite
    sqlite_conn = sqlite3.connect(str(DB_PATH))
    sqlite_conn.row_factory = sqlite3.Row  # словари вместо tuples

    # Открываем сессию Postgres
    with SessionLocal() as pg_session:
        # === Проверка что Postgres пустой ===
        existing_users = pg_session.scalar(select(func.count()).select_from(User))
        if existing_users > 0:
            print(f"⚠️  В Postgres уже есть {existing_users} юзеров.")
            answer = input("Перезаписать? (y/N): ")
            if answer.lower() != "y":
                print("Отмена")
                return
            # Чистим таблицы в правильном порядке
            for table in ["counterparty_risks", "counterparties", "llm_calls", "processings", "users"]:
                pg_session.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
            pg_session.commit()
            print("🗑  Таблицы очищены\n")

        # === 1. users ===
        print("👤 Переношу users...")
        rows = sqlite_conn.execute("SELECT * FROM users").fetchall()
        for r in rows:
            user = User(
                id=r["id"],
                email=r["email"],
                api_key=r["api_key"],
                name=r["name"],
                telegram_chat_id=r["telegram_chat_id"],
                telegram_username=r["telegram_username"],
                preferred_delivery=r["preferred_delivery"] or "telegram",
                created_at=parse_dt(r["created_at"]),
            )
            pg_session.add(user)
        pg_session.flush()
        print(f"   ✅ {len(rows)} записей")

        # === 2. processings ===
        print("📄 Переношу processings...")
        rows = sqlite_conn.execute("SELECT * FROM processings").fetchall()
        for r in rows:
            processing = Processing(
                id=r["id"],
                file_hash=r["file_hash"],
                original_filename=r["original_filename"],
                status=r["status"],
                user_id=r["user_id"],
                created_at=parse_dt(r["created_at"]),
                completed_at=parse_dt(r["completed_at"]),
                result_path=r["result_path"],
                error_message=r["error_message"],
                delivery_channel=r["delivery_channel"],
                delivery_status=r["delivery_status"],
                delivery_attempt_count=r["delivery_attempt_count"] or 0,
                delivery_error=r["delivery_error"],
                delivered_at=parse_dt(r["delivered_at"]),
            )
            pg_session.add(processing)
        pg_session.flush()
        print(f"   ✅ {len(rows)} записей")

        # === 3. llm_calls ===
        print("🤖 Переношу llm_calls...")
        rows = sqlite_conn.execute("SELECT * FROM llm_calls").fetchall()
        for r in rows:
            llm_call = LLMCall(
                id=r["id"],
                processing_id=r["processing_id"],
                user_id=r["user_id"],
                model=r["model"],
                stage=r["stage"],
                tokens_in=r["tokens_in"],
                tokens_out=r["tokens_out"],
                latency_ms=r["latency_ms"],
                cost_usd=r["cost_usd"],
                status=r["status"] or "success",
                created_at=parse_dt(r["created_at"]),
            )
            pg_session.add(llm_call)
        pg_session.flush()
        print(f"   ✅ {len(rows)} записей")

        # === 4. counterparties ===
        print("🏢 Переношу counterparties...")
        rows = sqlite_conn.execute("SELECT * FROM counterparties").fetchall()
        for r in rows:
            cp = Counterparty(
                user_id=r["user_id"],
                inn=r["inn"],
                name=r["name"],
                times_seen=r["times_seen"] or 1,
                first_seen=parse_dt(r["first_seen"]),
                last_seen=parse_dt(r["last_seen"]),
            )
            pg_session.add(cp)
        pg_session.flush()
        print(f"   ✅ {len(rows)} записей")

        # === 5. counterparty_risks ===
        print("⚠️  Переношу counterparty_risks...")
        rows = sqlite_conn.execute("SELECT * FROM counterparty_risks").fetchall()
        for r in rows:
            risk = CounterpartyRisk(
                id=r["id"],
                user_id=r["user_id"],
                counterparty_inn=r["counterparty_inn"],
                processing_id=r["processing_id"],
                document_number=r["document_number"],
                risk_text=r["risk_text"],
                severity=r["severity"] or "MEDIUM",
                found_at=parse_dt(r["found_at"]),
            )
            pg_session.add(risk)
        pg_session.flush()
        print(f"   ✅ {len(rows)} записей")

        # === Синхронизация SEQUENCE ===
        # Postgres хранит "следующий id" в sequence. Мы вставили с ручными id,
        # надо сдвинуть sequence чтобы новые записи не конфликтовали.
        print("\n🔧 Синхронизирую sequences...")
        for table in ["users", "processings", "llm_calls", "counterparty_risks"]:
            pg_session.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 1), true)"
            ))

        pg_session.commit()
        print("\n🎉 Миграция завершена")

    sqlite_conn.close()


if __name__ == "__main__":
    migrate()