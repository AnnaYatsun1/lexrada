"""WorkerContext — dependency injection для orchestrator."""
from dataclasses import dataclass

from execution.agents.orchestrator import MultiAgentOrchestrator
from execution.services.extraction import ExtractionService
from execution.services.notifier import NotifierManager
from execution.gateways.llm import AnthropicLLM
from execution.services.pricing import PricingService


@dataclass
class WorkerContext:
    """
    Контейнер с сервисами для процесса обработки договора.
    Создаётся один раз при старте worker'а (Celery / CLI / API).
    """
    llm: AnthropicLLM
    extraction_service: ExtractionService
    orchestrator: MultiAgentOrchestrator
    pricing_service: PricingService
    notifier_manager: NotifierManager