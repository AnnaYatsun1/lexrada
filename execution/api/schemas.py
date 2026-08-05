"""
API schemas — Pydantic модели для запросов и ответов API.
Отдельно от моделей extraction/analysis — это публичный интерфейс API.
"""
from pydantic import BaseModel
from typing import Optional
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


# ===== ОТВЕТЫ =====

class AnalyzeResponse(BaseModel):
    """Ответ на POST /analyze — задача принята"""
    processing_id: str
    celery_task_id: str
    status: TaskStatus
    message: str


class PartyOut(BaseModel):
    """Сторона договора в ответе API"""
    name: str
    role: Optional[str] = None
    inn: Optional[str] = None
    ogrn: Optional[str] = None


class ResultResponse(BaseModel):
    """Ответ на GET /result/{task_id}"""
    task_id: str
    status: TaskStatus
    doc_type: Optional[str] = None
    document_number: Optional[str] = None
    document_date: Optional[str] = None
    parties: list[PartyOut] = []
    subject: Optional[str] = None
    price: Optional[str] = None
    risk_level: Optional[str] = None
    risk_report: Optional[str] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Ответ на GET /health"""
    status: str
    version: str