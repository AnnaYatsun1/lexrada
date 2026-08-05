"""Celery task для обработки договора."""
from pathlib import Path
from functools import lru_cache

import anthropic

from execution.agents.orchestrator import MultiAgentOrchestrator
from execution.services.pricing import PricingService
from execution.tasks.celery_app import celery
from execution.orchestration.context import WorkerContext
from execution.orchestration.process_contract import process_contract
from execution.gateways.llm import AnthropicLLM
from execution.gateways.vectors import ChromaStore
from execution.services.extraction import ExtractionService
from execution.services.factory.factory import build_notifier_for_user
from execution.database.session import SessionLocal
from execution.repositories.users import UserRepository
from execution.repositories.processings import ProcessingRepository
from execution.lodder.logger import get_logger
from paths import DIRECTIVES_DIR

logger = get_logger("celery.analyze")


# Transient errors — Celery делает retry
TRANSIENT_ERRORS = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


@lru_cache
def _build_context_for_user(user_id: int) -> WorkerContext:
    """Кешируется на воркере — сервисы создаются один раз для юзера."""
    client = anthropic.Anthropic(timeout=60)
    llm = AnthropicLLM(client)

    extraction = ExtractionService(
        llm=llm,
        directive=(DIRECTIVES_DIR / "contract_analysis.md").read_text(encoding="utf-8"),
    )
    orchestrator = MultiAgentOrchestrator(
        llm=llm,
        vectors=ChromaStore(),
        compliance_directive=(DIRECTIVES_DIR / "risk_analysis.md").read_text(encoding="utf-8"),
    )

    with SessionLocal() as session:
        user = UserRepository(session).get_by_id(user_id)
        user_data = {
            "id": user.id,
            "telegram_chat_id": user.telegram_chat_id,
            "email": user.email,
            "preferred_delivery": user.preferred_delivery,
        }
    notifier = build_notifier_for_user(user_data)

    return WorkerContext(
        llm=llm,
        extraction_service=extraction,
        orchestrator=orchestrator,
        pricing_service=PricingService(),
        notifier_manager=notifier,
    )


@celery.task(
    bind=True,
    max_retries=3,
    autoretry_for=TRANSIENT_ERRORS,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
)
def analyze_contract_task(self, processing_id: int, file_path_str: str, user_id: int):
    """
    Celery-задача обработки договора.

    Retry — только на transient errors (сеть, rate limit, 5xx Anthropic).
    Permanent errors (битый файл, невалидные данные) → сразу помечаем 
    processing.status = failed, чтобы клиент через GET /result увидел ошибку.
    """
    file_path = Path(file_path_str)

    try:
        ctx = _build_context_for_user(user_id)
        logger.warning(
        "Analysis service in WorkerContext: %s.%s",
        type(ctx.orchestrator).__module__,
        type(ctx.orchestrator).__name__,    
    )
        process_contract(ctx, processing_id, file_path, user_id)
        logger.info(f"Task succeeded: processing_id={processing_id}")
    
    except TRANSIENT_ERRORS as e:
        # Celery сам сделает retry (см. autoretry_for в декораторе).
        # На последнем retry, если снова упадёт — попадёт в общий except ниже.
        logger.warning(
            f"Transient error, retry {self.request.retries + 1}/{self.max_retries}: {e}"
        )
        raise

    except Exception as e:
        # Permanent error или все retry исчерпаны.
        # Обновляем processing.status чтобы клиент увидел через GET /result.
        logger.exception(f"Task permanently failed: processing_id={processing_id}")
        _mark_processing_failed(processing_id, str(e))
        raise  # re-raise чтобы Celery залогировал FAILED


def _mark_processing_failed(processing_id: int, error_message: str):
    """
    Обновляет processing.status = 'failed' в отдельной сессии.
    Изолированная транзакция — не связана с основной обработкой.
    """
    try:
        with SessionLocal() as session:
            ProcessingRepository(session).mark_failure(processing_id, error_message)
            session.commit()
    except Exception as e:
        logger.error(f"Failed to update processing {processing_id} status: {e}")