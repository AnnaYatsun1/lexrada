"""Compliance Agent — проверяет соответствие договора нормам законодательства."""
import logging
from execution.services.analysis import AnalysisService
from execution.models.analysis import RiskAnalysis
from execution.gateways.llm import LLMGateway
from execution.gateways.vectors import VectorStore

logger = logging.getLogger(__name__)


class ComplianceAgent:
    """
    Проверяет договор на соответствие нормам права.
    Использует RAG + self-reflection.
    """

    def __init__(self, llm: LLMGateway, vectors: VectorStore, directive: str):
        self._service = AnalysisService(llm=llm, vectors=vectors, directive=directive)

    def analyze(
        self,
        contract_json,
        processing_id: int,
        user_id: int,
        rag_filter: dict | None = None,
        extra_context: str | None = None,
    ) -> RiskAnalysis:
        logger.info(f"ComplianceAgent started: processing_id={processing_id}")
        result = self._service.analyze(
            contract_json=contract_json,
            processing_id=processing_id,
            user_id=user_id,
            extra_context=extra_context,
            rag_filter=rag_filter,
            enable_reflection=True,
        )
        logger.info(f"ComplianceAgent done: score={result.score}, risks={len(result.risks)}")
        return result