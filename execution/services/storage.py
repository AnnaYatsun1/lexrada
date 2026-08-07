"""Работа с файлами: uploads, results, temporary files."""
from pathlib import Path

from execution.database.models import Processing
from sqlalchemy.orm import Session


class StorageService:
    
    def __init__(self, session: Session):
        self._session = session

    def save_file(self, processing_id: int, content: bytes) -> None:
        processing = self._session.get(Processing, processing_id)
        if processing is None:
            raise ValueError(f"Processing {processing_id} not found")
        processing.file_content = content

    def read_file(self, processing_id: int) -> bytes:
        processing = self._session.get(Processing, processing_id)
        if processing is None or processing.file_content is None:
            raise FileNotFoundError(
                f"File content not found for processing {processing_id}"
            )
        return processing.file_content

    def delete(self, processing_id: int) -> None:
        """Обнуляет содержимое после обработки — не держим файлы в БД вечно."""
        processing = self._session.get(Processing, processing_id)
        if processing is not None:
            processing.file_content = None

    def exists(self, processing_id: int) -> bool:
        processing = self._session.get(Processing, processing_id)
        return processing is not None and processing.file_content is not None