"""
AnthropicLLM — единственное место с вызовом Anthropic + retry + метрики + tracing.

Пишет:
- Langfuse trace (для observability)
- LLMCall в БД через LLMCallRepository (для биллинга и аналитики)
"""
import time
import logging
from typing import Protocol, Any

import anthropic
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, before_sleep_log,
)
from langfuse import get_client

from execution.database.session import SessionLocal
# from execution.pricing.service import PricingService
# from execution.repositories.llm_calls import LLMCallRepository
from execution.lodder.logger import get_logger
from execution.repositories.llm_call import LLMCallRepository
from execution.services.pricing import PricingService

logger = get_logger(__name__)
langfuse = get_client()

# PricingService на весь модуль — stateless, безопасно
_pricing = PricingService()

_RETRYABLE = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


class LLMGateway(Protocol):
    def create(self, *, model: str, messages: list[dict], stage: str,
               processing_id: int | None = None, user_id: int | None = None,
               tools: list[dict] | None = None,
               tool_choice: dict | None = None,
               max_tokens: int = 2000,
               system: Any = None) -> anthropic.types.Message: ...


class AnthropicLLM:
    """Обёртка над Anthropic API: retry, Langfuse trace, запись метрики."""

    def __init__(self, client: anthropic.Anthropic):
        self._client = client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def create(
        self, *,
        model,
        messages,
        stage,
        processing_id=None,
        user_id=None,
        tools=None,
        tool_choice=None,
        max_tokens=2000,
        system=None,
    ):
        start = time.time()
        kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": messages}
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        if system is not None:
            kwargs["system"] = system

        metadata = {"has_tools": tools is not None}
        if user_id is not None:
            metadata["user_id"] = user_id
        if processing_id is not None:
            metadata["processing_id"] = processing_id

        # Langfuse trace
        with langfuse.start_as_current_observation(
            as_type="generation",
            name=stage,
            model=model,
            input=messages,
            metadata=metadata,
        ) as generation:
            resp = self._client.messages.create(**kwargs)
            content_debug = [
                    block.model_dump()
                    if hasattr(block, "model_dump")
                    else repr(block)
                    for block in resp.content
                ]

            with langfuse.start_as_current_observation(
                as_type="generation",
                name=stage,
                model=model,
                input=messages,
                metadata=metadata,
            ) as generation:

                logger.warning(
                "ANTHROPIC REQUEST | "
                "stage=%s | tool_choice=%s | tools=%s | max_tokens=%s",
                stage,
                tool_choice,
                [tool.get("name") for tool in tools] if tools else [],
                max_tokens,
            )

            resp = self._client.messages.create(**kwargs)
            content_debug = [
                block.model_dump()
                if hasattr(block, "model_dump")
                else repr(block)
                for block in resp.content
            ]

            logger.warning(
                "ANTHROPIC RESPONSE | "
                "stage=%s | stop_reason=%s | content=%s",
                stage,
                resp.stop_reason,
                content_debug,
            )
            generation.update(
                output=resp.content,
                usage_details={
                    "input": resp.usage.input_tokens,
                    "output": resp.usage.output_tokens,
                },
                metadata={
                    **metadata,
                    "tool_choice": tool_choice,
                    "tool_names": [
                        tool.get("name") for tool in tools
                    ] if tools else [],
                    "stop_reason": resp.stop_reason,
                },
    )
            generation.update(
                output=resp.content,
                usage_details={
                    "input": resp.usage.input_tokens,
                    "output": resp.usage.output_tokens,
                },
            )

        # Запись метрики через репозиторий (только для production-вызовов)
        if processing_id is not None:
            self._record_metric(
                processing_id=processing_id,
                model=model,
                stage=stage,
                tokens_in=resp.usage.input_tokens,
                tokens_out=resp.usage.output_tokens,
                latency_ms=int((time.time() - start) * 1000),
            )

        return resp

    def _record_metric(
        self,
        processing_id: int,
        model: str,
        stage: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
    ):
        """
        Пишет LLMCall в БД через репозиторий.
        
        Открывает свою сессию — не переиспользуем ту что может быть в вызывающем.
        Если запись упадёт (БД недоступна) — только логируем, не роняем pipeline:
        LLM-вызов уже успешный, а потеря метрики не критична для юзера.
        """
        cost_usd = _pricing.calculate(model, tokens_in, tokens_out)
        try:
            with SessionLocal() as session:
                LLMCallRepository(session).record(
                    processing_id=processing_id,
                    model=model,
                    stage=stage,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=latency_ms,
                    cost_usd=cost_usd,
                )
                session.commit()
        except Exception as e:
            logger.warning(f"Failed to record LLM metric: {e}")