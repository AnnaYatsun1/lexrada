import os
import logging
from pathlib import Path

import requests
from fastapi import APIRouter, Request, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from execution.api.dependencies import (
    get_db_session,
    get_processing_repository,
    get_storage_service,
)
from execution.repositories.processings import ProcessingRepository
from execution.repositories.users import UserRepository
from execution.services.storage import StorageService
from execution.tasks.analyze import analyze_contract_task
from execution.utils.hashing import compute_content_hash

logger = logging.getLogger("telegram_webhook")

router = APIRouter(prefix="/telegram", tags=["telegram"])

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET")

ALLOWED_SUFFIXES = (".txt", ".pdf", ".docx")
MAX_FILE_SIZE = 20 * 1024 * 1024  # Bot API отдаёт файлы до 20 МБ


def _send_message(chat_id: int, text: str) -> None:
    """Быстрый ответ в чат (ack / ошибки). Без retry — не критично."""
    if not TELEGRAM_TOKEN:
        logger.warning("TELEGRAM_TOKEN не задан, не могу ответить в чат")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
    except Exception as e:
        logger.warning(f"Не смог ответить в Telegram: {e}")


def _download_file(file_id: str) -> bytes:
    """getFile → скачивание содержимого из Telegram."""
    resp = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile",
        params={"file_id": file_id},
        timeout=30,
    )
    resp.raise_for_status()
    file_path = resp.json()["result"]["file_path"]

    file_resp = requests.get(
        f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}",
        timeout=60,
    )
    file_resp.raise_for_status()
    return file_resp.content


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    session: Session = Depends(get_db_session),
    processing_repo: ProcessingRepository = Depends(get_processing_repository),
    storage: StorageService = Depends(get_storage_service),
):
    # ─── Проверка секрета вебхука ───
    if WEBHOOK_SECRET and x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    update = await request.json()
    message = update.get("message") or update.get("channel_post")
    if not message:
        return {"ok": True}  # edited / callback и т.п. — игнорируем

    chat_id = message["chat"]["id"]
    document = message.get("document")

    if not document:
        _send_message(chat_id, "Пришлите договор файлом (.txt, .pdf или .docx).")
        return {"ok": True}

    filename = document.get("file_name", "document")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        _send_message(chat_id, f"Формат {suffix} не поддерживается. Нужен .txt, .pdf или .docx.")
        return {"ok": True}

    if document.get("file_size", 0) > MAX_FILE_SIZE:
        _send_message(chat_id, "Файл слишком большой (лимит 20 МБ).")
        return {"ok": True}

    # ─── Резолвим юзера по chat_id (аналог API-key auth для бота) ───
    user = UserRepository(session).get_by_telegram_chat_id(str(chat_id))
    if not user:
        _send_message(chat_id, "Вы не зарегистрированы. Обратитесь к администратору.")
        return {"ok": True}
    user_id = user.id

    # ─── Скачиваем файл ───
    try:
        content = _download_file(document["file_id"])
    except Exception:
        logger.exception("Не удалось скачать файл из Telegram")
        _send_message(chat_id, "Не смог скачать файл, попробуйте ещё раз.")
        return {"ok": True}

    # ─── Дальше — ровно как в POST /analyze ───
    processing = processing_repo.create(
        file_hash=compute_content_hash(content),
        filename=filename,
        user_id=user_id,
    )
    processing_id = processing.id
    session.commit()

    file_path = storage.save_upload(content, processing_id, filename)

    task = analyze_contract_task.delay(
        processing_id=processing_id,
        file_path_str=str(file_path),
        user_id=user_id,
    )
    processing_repo.set_celery_task_id(processing_id, task.id)
    session.commit()

    _send_message(chat_id, f"📄 Принял «{filename}». Анализирую, отчёт пришлю сюда же.")
    return {"ok": True}