"""
Создаёт dev-юзера Anna в Postgres.

Идемпотентный — можно запускать много раз, не создаст дубликат.

Запуск из корня:
    python3 -m scripts.setup_dev_user
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from execution.database.session import SessionLocal
from execution.repositories.users import UserRepository


DEV_USER = {
    "api_key": "test-api-key-001",
    "email": "anna@lexradar.local",
    "name": "Anna",
    "telegram_chat_id": "258858232",
    "preferred_delivery": "telegram",
}


def setup():
    with SessionLocal() as session:
        user_repo = UserRepository(session)

        existing = user_repo.get_by_api_key(DEV_USER["api_key"])
        if existing:
            print(f"✅ Юзер уже существует: id={existing.id}, name={existing.name}")
            return

        user = user_repo.create(**DEV_USER)
        session.commit()
        print(f"✅ Создан dev-юзер: id={user.id}, name={user.name}, api_key={user.api_key}")


if __name__ == "__main__":
    setup()