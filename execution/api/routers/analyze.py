"""POST /analyze → создаёт processing, отправляет в Celery, возвращает processing_id."""
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from execution.api.dependencies import (
    get_current_user,
    get_db_session,
    get_processing_repository,
    get_storage_service,
)
from execution.api.schemas import AnalyzeResponse, ResultResponse, TaskStatus
from execution.database.models import User
from execution.repositories.processings import ProcessingRepository, ProcessingStatus
from execution.services.storage import StorageService
from execution.tasks.analyze import analyze_contract_task
from execution.utils.hashing import compute_content_hash

router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    processing_repo: ProcessingRepository = Depends(get_processing_repository),
    storage: StorageService = Depends(get_storage_service),
) -> AnalyzeResponse:
    """
    Принимает файл, кладёт задачу в очередь, возвращает processing_id.
    """
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".txt", ".pdf", ".docx"):
        raise HTTPException(status_code=400, detail=f"Неподдерживаемый формат: {suffix}")

    content = await file.read()

    # 1. Создаём processing
    processing = processing_repo.create(
        file_hash=compute_content_hash(content),
        filename=file.filename,
        user_id=current_user.id,
    )
    processing_id = processing.id
    session.commit()

    storage.save_file(processing_id, content)
    session.commit()

    task = analyze_contract_task.delay(
        processing_id=processing_id,
        filename=file.filename,
        user_id=current_user.id,
    )

    # 4. Сохраняем Celery task_id для трассировки
    processing_repo.set_celery_task_id(processing_id, task.id)
    session.commit()

    return AnalyzeResponse(
        processing_id=processing_id,
        celery_task_id = str(task.id),
        status=TaskStatus.PROCESSING,
        message=f"Задача принята. Celery task: {task.id}",
    )


@router.get("/result/{processing_id}", response_model=ResultResponse)
def get_result(
    processing_id: int,
    current_user: User = Depends(get_current_user),
    processing_repo: ProcessingRepository = Depends(get_processing_repository),
) -> ResultResponse:
    """Статус обработки. Опрашивай до status=done или status=error."""
    processing = processing_repo.get_for_user(processing_id, current_user.id)
    if not processing:
        raise HTTPException(status_code=404, detail=f"Processing {processing_id} not found")

    # Маппинг ProcessingStatus (БД) → TaskStatus (API)
    if processing.status == ProcessingStatus.PROCESSING.value:
        return ResultResponse(
            task_id=str(processing_id),
            status=TaskStatus.PROCESSING,
        )

    if processing.status == ProcessingStatus.FAILED.value:
        return ResultResponse(
            task_id=str(processing_id),
            status=TaskStatus.ERROR,
            error=processing.error_message,
        )

    # ProcessingStatus.DONE
    return ResultResponse(
        task_id=str(processing_id),
        status=TaskStatus.DONE,
    )