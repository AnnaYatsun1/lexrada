"""
dependencies.py — зависимости для FastAPI.
Services создаются один раз при старте, не пересоздаются при каждом запросе.
Аналог Swift: singleton / dependency injection.
"""
from functools import lru_cache
from pathlib import Path
from typing import Generator
import anthropic

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from execution.database.models import User
from execution.database.session import SessionLocal
from execution.gateways.llm import AnthropicLLM
from execution.gateways.vectors import ChromaStore
from execution.repositories.counterparty import CounterpartyRepository
from execution.repositories.counterparty_risk import CounterpartyRiskRepository
from execution.repositories.processings import ProcessingRepository
from execution.repositories.users import UserRepository
from execution.services.extraction import ExtractionService
from execution.services.analysis import AnalysisService
from execution.database.db import get_user_by_api_key
from execution.services.storage import StorageService
from execution.repositories.reviews import ReviewRepository
from execution.services.review import ReviewService
from paths import DIRECTIVES_DIR


@lru_cache
def get_llm() -> AnthropicLLM:
    """Один клиент Anthropic на всё приложение"""
    client = anthropic.Anthropic(timeout=60)
    return AnthropicLLM(client)


@lru_cache
def get_extraction_service() -> ExtractionService:
    return ExtractionService(
        llm=get_llm(),
        directive=Path(DIRECTIVES_DIR / "contract_analysis_v2.md").read_text(encoding="utf-8"),
    )


@lru_cache
def get_analysis_service() -> AnalysisService:
    return AnalysisService(
        llm=get_llm(),
        vectors=ChromaStore(),
        directive=Path(DIRECTIVES_DIR / "risk_analysis.md").read_text(encoding="utf-8"),
    )

def get_db_session() -> Generator[Session, None, None]:
    """
    Даёт сессию для одного HTTP-запроса.
    После ответа сессия автоматически закрывается.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

def get_user_repository(session = Depends(get_db_session)) -> UserRepository:
    return UserRepository(session)

def get_processing_repository(session = Depends(get_db_session)) -> ProcessingRepository:
    return ProcessingRepository(session)

def get_counterparty_repository(session = Depends(get_db_session)) -> CounterpartyRepository:
    return CounterpartyRepository(session)

def get_current_user(
        x_api_key: str = Header(..., alias="X-API-Key"),
        repository: UserRepository = Depends(get_user_repository),
        )  -> User:
    user = repository.get_by_api_key(x_api_key)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key",
        )

    return user

def get_processing_repository(
    session: Session = Depends(get_db_session),
) -> ProcessingRepository:
    """Фабрика ProcessingRepository для текущего запроса."""
    return ProcessingRepository(session)


def get_counterparty_repository(
    session: Session = Depends(get_db_session),
) -> CounterpartyRepository:
    """Фабрика CounterpartyRepository для текущего запроса."""
    return CounterpartyRepository(session)


def get_counterparty_risk_repository(
    session: Session = Depends(get_db_session),
) -> CounterpartyRiskRepository:
    """Фабрика CounterpartyRiskRepository для текущего запроса."""
    return CounterpartyRiskRepository(session)

@lru_cache
def get_storage_service() -> StorageService:
    """Singleton — один инстанс на приложение."""
    return StorageService()

def get_review_repository(
    session: Session = Depends(get_db_session),
) -> ReviewRepository:
    """ReviewRepository для текущего HTTP-запроса."""
    return ReviewRepository(session)


def get_review_service(
    session: Session = Depends(get_db_session),
    processing_repository: ProcessingRepository = Depends(
        get_processing_repository
    ),
    review_repository: ReviewRepository = Depends(
        get_review_repository
    ),
    storage_service: StorageService = Depends(
        get_storage_service
    ),
) -> ReviewService:
    """ReviewService для текущего HTTP-запроса."""
    return ReviewService(
        session=session,
        processing_repository=processing_repository,
        review_repository=review_repository,
        storage_service=storage_service,
    )