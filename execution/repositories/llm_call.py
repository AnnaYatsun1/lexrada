
from execution.repositories.base import BaseRepository


"""Репозиторий для метрик LLM-вызовов."""
from datetime import datetime, UTC

from sqlalchemy import select, func

from execution.repositories.base import BaseRepository
from execution.database.models import LLMCall, Processing

class LLMCallRepository(BaseRepository[LLMCall]):
    model = LLMCall

    def record(
        self,
        processing_id: int,
        model: str,
        stage: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        cost_usd: float,
        status: str = "success",
        
    ) -> LLMCall:
        """
        Залогировать LLM-вызов.
        
        user_id берётся автоматически из processing — защита от рассинхронизации.
        Стоимость считается автоматически по PRICING.
        """
        processing = self.session.get(Processing, processing_id)
        if processing is None:
            raise ValueError(f"Processing {processing_id} not found")

        llm_call = LLMCall(
            processing_id=processing.id,
            user_id=processing.user_id,          # ← защита: берём от processing
            model=model,
            stage=stage,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            status=status,
            created_at=datetime.now(UTC),
        )
        self.add(llm_call)
        return llm_call

    def total_cost_by_user(
        self,
        user_id: int,
        since: datetime | None = None,
    ) -> float:
        """
        Сколько потратил юзер (для биллинга).
        
        Пример:
            with get_session() as s:
                repo = LLMCallRepository(s)
                total = repo.total_cost_by_user(user_id=1, since=datetime(2026, 7, 1))
        """
        stmt = select(func.coalesce(func.sum(LLMCall.cost_usd), 0.0)).where(
            LLMCall.user_id == user_id
        )
        if since is not None:
            stmt = stmt.where(LLMCall.created_at >= since)
        return float(self.session.scalar(stmt) or 0.0)

    def cost_breakdown_by_stage(self, user_id: int) -> dict[str, float]:
        """
        Разбивка стоимости по этапам (extract/analyze/summary) для юзера.
        Полезно для дашбордов.
        """
        stmt = (
            select(LLMCall.stage, func.sum(LLMCall.cost_usd))
            .where(LLMCall.user_id == user_id)
            .group_by(LLMCall.stage)
        )
        return {stage: float(cost) for stage, cost in self.session.execute(stmt).all()}