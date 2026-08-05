"""Orchestrator — запускает агентов параллельно через ThreadPoolExecutor."""
import logging
# from concurrent.futures import ThreadPoolExecutor, as_completed
from execution.agents.compliance_agent import ComplianceAgent
from execution.agents.risk_agent import RiskAgent
from execution.agents.final_reviewer import FinalReviewer
from execution.models.analysis import RiskAnalysis
from execution.gateways.llm import LLMGateway
from execution.gateways.vectors import VectorStore

logger = logging.getLogger(__name__)


class MultiAgentOrchestrator:
    """
    Оркестрирует параллельный запуск агентов.
    
    Flow:
        1. ComplianceAgent + RiskAgent запускаются параллельно
        2. FinalReviewer объединяет результаты
    """

    def __init__(
        self,
        llm: LLMGateway,
        vectors: VectorStore,
        compliance_directive: str,
    ):
        self._compliance_agent = ComplianceAgent(
            llm=llm,
            vectors=vectors,
            directive=compliance_directive,
        )
        self._risk_agent = RiskAgent(llm=llm)
        self._final_reviewer = FinalReviewer(llm=llm)

    def analyze(
    self,
    contract_json,
    processing_id: int,
    user_id: int,
    rag_filter: dict | None = None,
    extra_context: str | None = None,
) -> RiskAnalysis:
        logger.warning(
        "MULTI-AGENT ORCHESTRATOR ENTERED: processing_id=%s",
        processing_id,
    )

        compliance_result = self._compliance_agent.analyze(
            contract_json=contract_json,
            processing_id=processing_id,
            user_id=user_id,
            rag_filter=rag_filter,
            extra_context=extra_context,
        )

        logger.warning(
            "COMPLIANCE COMPLETED: processing_id=%s",
            processing_id,
        )

        risk_result = self._risk_agent.analyze(
            contract_json=contract_json,
            processing_id=processing_id,
            user_id=user_id,
        )

        logger.warning(
            "RISK AGENT COMPLETED: processing_id=%s",
            processing_id,
        )

        final_result = self._final_reviewer.review(
            compliance_result=compliance_result,
            risk_result=risk_result,
            contract_json=contract_json,
            processing_id=processing_id,
            user_id=user_id,
        )

        logger.warning(
            "FINAL REVIEW COMPLETED: processing_id=%s",
            processing_id,
        )

        return final_result

    # def analyze(
    #     self,
    #     contract_json,
    #     processing_id: int,
    #     user_id: int,
    #     rag_filter: dict | None = None,
    #     extra_context: str | None = None,
    # ) -> RiskAnalysis:
    #     logger.info(f"MultiAgentOrchestrator started: processing_id={processing_id}")

    #     compliance_result = None
    #     risk_result = None

    #     # Параллельный запуск агентов
    #     with ThreadPoolExecutor(max_workers=2) as executor:
    #         futures = {
    #             executor.submit(
    #                 self._compliance_agent.analyze,
    #                 contract_json, processing_id, user_id,
    #                 rag_filter, extra_context,
    #             ): "compliance",
    #             executor.submit(
    #                 self._risk_agent.analyze,
    #                 contract_json, processing_id, user_id,
    #             ): "risk",
    #         }

    #         for future in as_completed(futures):
    #             agent_name = futures[future]
    #             try:
    #                 result = future.result()
    #                 if agent_name == "compliance":
    #                     compliance_result = result
    #                 else:
    #                     risk_result = result
    #                 logger.info(f"{agent_name} agent completed")
    #             except Exception as e:
    #                 logger.error(f"{agent_name} agent failed: {e}")
    #                 # Не поднимаем ошибку — продолжаем с тем что есть

    #         # После цикла — проверяем что получили
    #         if compliance_result is None and risk_result is None:
    #             raise RuntimeError("Оба агента завершились с ошибкой")

    #         if risk_result is None:
    #             logger.warning("RiskAgent failed — partial analysis (compliance only)")
    #             # Помечаем в отчёте что анализ частичный
    #             return RiskAnalysis(
    #                 report_md=(
    #                     f"⚠️ **Частичный анализ** — Risk Agent недоступен.\n\n"
    #                     f"{compliance_result.report_md}"
    #                 ),
    #                 risk_level=compliance_result.risk_level,
    #                 score=compliance_result.score,
    #                 risks=compliance_result.risks,
    #                 recommendation=compliance_result.recommendation,
    #             )

    #         if compliance_result is None:
    #             logger.warning("ComplianceAgent failed — partial analysis (risk only)")
    #             return RiskAnalysis(
    #                 report_md=(
    #                     f"⚠️ **Частичный анализ** — Compliance Agent недоступен.\n\n"
    #                     f"{risk_result.report_md}"
    #                 ),
    #                 risk_level=risk_result.risk_level,
    #                 score=risk_result.score,
    #                 risks=risk_result.risks,
    #                 recommendation=risk_result.recommendation,
    #             )

    #     # Final Reviewer объединяет
    #     final = self._final_reviewer.review(
    #         compliance_result=compliance_result,
    #         risk_result=risk_result,
    #         contract_json=contract_json,
    #         processing_id=processing_id,
    #         user_id=user_id,
    #     )

    #     logger.info(f"MultiAgentOrchestrator done: score={final.score}")
    #     return final