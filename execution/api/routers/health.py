"""
health.py — эндпоинт проверки состояния сервера.
GET /health → {"status": "ok", "version": "0.1.0"}
"""
from fastapi import APIRouter

from execution.api.schemas import HealthResponse


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version="0.1.0")