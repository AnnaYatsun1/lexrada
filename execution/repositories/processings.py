
from execution.database.models import Processing
from execution.repositories.base import BaseRepository

"""Репозиторий для работы с обработками договоров."""
from datetime import datetime, UTC
from enum import Enum 
from sqlalchemy import select


class ProcessingStatus(str, Enum):
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed" 
    PENDING_REVIEW = "pending_review" 
    APPROVED = "approved"              
    REJECTED = "rejected"   


class ReviewDecision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class DeliveryStatus(str, Enum):
    SENT = "sent"
    FAILED = "failed"
    PENDING = "pending"
    
class ProcessingRepository(BaseRepository[Processing]):
    model = Processing

    def create(self, file_hash: str, filename: str, user_id: int) -> Processing:
        """Создать запись о начале обработки. Возвращает объект с готовым id."""
        processing = Processing(
            file_hash=file_hash,
            original_filename=filename,
            status= ProcessingStatus.PROCESSING.value,
            user_id=user_id,
            created_at=datetime.now(UTC),
        )
        self.add(processing)
        self.session.flush()  # чтобы получить сгенерированный id
        return processing

    def exists_completed(self, file_hash: str, user_id: int) -> bool:
        """
        Проверить, обработан ли уже этот файл ЭТИМ юзером.
        Идемпотентность per-user: один файл у разных юзеров — разные обработки.
        """
        stmt = select(Processing).where(
            Processing.file_hash == file_hash,
            Processing.status == ProcessingStatus.DONE.value,
            Processing.user_id == user_id,
        )
        return self.session.scalar(stmt) is not None

    def mark_success(self, processing_id: int, result_path: str) -> None:
        """Пометить обработку как успешную."""
        processing = self.get_by_id(processing_id)
        if processing is None:
            raise ValueError(f"Processing {processing_id} not found")
        
        processing.status = ProcessingStatus.DONE.value
        processing.completed_at = datetime.now(UTC)
        processing.result_path = result_path

    def mark_failure(self, processing_id: int, error_message: str) -> None:
        """Пометить обработку как упавшую."""
        processing = self.get_by_id(processing_id)
        if processing is None:
            return
        processing.status = ProcessingStatus.FAILED.value
        processing.completed_at = datetime.now(UTC)
        processing.error_message = error_message

    def record_delivery_attempt(
        self,
        processing_id: int,
        channel: str,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        """Залогировать попытку доставки отчёта."""
        processing = self.get_by_id(processing_id)
        if processing is None:
            raise ValueError(f"Processing {processing_id} not found")
        processing.delivery_channel = channel
        processing.delivery_status = DeliveryStatus.SENT.value if success else DeliveryStatus.FAILED.value
        processing.delivery_attempt_count = (processing.delivery_attempt_count or 0) + 1
        processing.delivery_error = None if success else error_message
        processing.delivered_at = datetime.now(UTC) if success else None

    def list_by_user(self, user_id: int, limit: int = 100, offset: int = 0) -> list[Processing]:
        """Получить обработки конкретного юзера (для API GET /my/processings)."""
        stmt = (
            select(Processing)
            .where(Processing.user_id == user_id)
            .order_by(Processing.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt).all())
    
    def set_celery_task_id(self, processing_id: int, celery_task_id: str) -> None:
        """Сохраняет ID Celery-задачи для трассировки."""
        processing = self.get_by_id(processing_id)
        if processing is None:
            raise ValueError(f"Processing {processing_id} not found")
        processing.celery_task_id = celery_task_id

    def list_pending_review(self, user_id: int) -> list[Processing]:
        stmt = (
            select(Processing)
            .where(
                Processing.user_id == user_id,
                Processing.status == ProcessingStatus.PENDING_REVIEW.value,
        )
        .order_by(Processing.created_at.asc())
    )
        return list(self.session.scalars(stmt).all())

    def mark_pending_review(self, processing_id: int, result_path: str) -> None:
        processing = self.get_by_id(processing_id)
        if processing is None:
            raise ValueError(f"Processing {processing_id} not found")
        processing.status = ProcessingStatus.PENDING_REVIEW.value
        processing.result_path = result_path
        processing.completed_at = datetime.now(UTC)
    def set_celery_task_id(
    self,
    processing_id: int,
    celery_task_id: str,
    ) -> None:
        """Сохраняет ID Celery-задачи для трассировки."""
        processing = self.get_by_id(processing_id)

        if processing is None:
            raise ValueError(
                f"Processing {processing_id} not found"
            )

        processing.celery_task_id = celery_task_id
        
    def get_for_user(self, processing_id: int, user_id: int) -> Processing | None:
        """Отдаёт processing ТОЛЬКО если он принадлежит user_id.
        Authz на уровне SQL — забыть проверку невозможно."""
        stmt = select(Processing).where(
            Processing.id == processing_id,
            Processing.user_id == user_id,
        )
        return self.session.scalar(stmt)