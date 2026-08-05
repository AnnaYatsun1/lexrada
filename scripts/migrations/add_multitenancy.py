"""Разовый скрипт: добавляет user_id в существующие таблицы + telegram-поля в users."""
import sqlite3
from datetime import datetime
from paths import DB_PATH
from execution.database.db import init_db

# сначала убедимся что таблица users существует
init_db()

conn = sqlite3.connect(DB_PATH)


def has_column(table, column):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    return column in cols


# === Шаг 1: расширяем таблицу users (если ещё не расширена) ===
for col, col_def in [
    ("telegram_chat_id", "TEXT"),
    ("telegram_username", "TEXT"),
    ("preferred_delivery", "TEXT DEFAULT 'telegram'"),
]:
    if not has_column("users", col):
        conn.execute(f"ALTER TABLE users ADD COLUMN {col} {col_def}")
        print(f"Добавлена колонка users.{col}")
    else:
        print(f"users.{col} уже существует — пропускаем")


# === Шаг 2: создаём/обновляем дефолтного юзера с telegram_chat_id ===
existing = conn.execute(
    "SELECT id FROM users WHERE email = ?",
    ("anna@lexradar.local",)
).fetchone()

if existing:
    user_id = existing[0]
    # обновим chat_id если его ещё нет
    conn.execute(
        "UPDATE users SET telegram_chat_id = ? WHERE id = ? AND (telegram_chat_id IS NULL OR telegram_chat_id = '')",
        ("258858232", user_id)
    )
    print(f"Юзер уже есть: id={user_id}, telegram_chat_id обновлён")
else:
    cursor = conn.execute(
        """INSERT INTO users (email, api_key, name, telegram_chat_id, preferred_delivery, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            "anna@lexradar.local",
            "test-api-key-001",
            "Anna",
            "258858232",
            "telegram",
            datetime.utcnow().isoformat()
        )
    )
    user_id = cursor.lastrowid
    print(f"Создан юзер: id={user_id}")


# === Шаг 3: добавляем user_id в существующие таблицы ===
for table in ["processings", "llm_calls", "counterparties", "counterparty_risks"]:
    if not has_column(table, "user_id"):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER")
        print(f"Добавлена колонка user_id в {table}")
    else:
        print(f"{table}.user_id уже существует — пропускаем")

    cursor = conn.execute(
        f"UPDATE {table} SET user_id = ? WHERE user_id IS NULL",
        (user_id,)
    )
    print(f"  → {table}: обновлено {cursor.rowcount} строк")


conn.commit()
conn.close()
print("\n Готово")