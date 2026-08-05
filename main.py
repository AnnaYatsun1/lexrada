"""
main.py — CLI-режим обработки договоров.

Использует репозитории вместо старого db.py.
"""
import os
import json
import logging
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

import app
from execution.repositories.llm_call import LLMCallRepository
from execution.services.pricing import PricingService
from execution.tasks.analyze import build_context_for_user
load_dotenv()
from execution.api.routers.review import router as review_router

from langfuse import observe, get_client
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, before_sleep_log,
)

from execution.gateways.llm import AnthropicLLM
from execution.gateways.vectors import ChromaStore
from execution.models.contract import AgreementContractOutput
from execution.models.rag import RetrieveDocumentsInput
from execution.services.analysis import AnalysisService
from execution.services.extraction import ExtractionService
from execution.services.classifier import DocumentParser
from execution.services.factory.factory import build_notifier_for_user

from execution.database.session import SessionLocal
from execution.repositories.users import UserRepository
from execution.repositories.processings import ProcessingRepository
from execution.repositories.counterparty import CounterpartyRepository
from execution.repositories.counterparty_risk import CounterpartyRiskRepository, RiskSeverity

from execution.utils.hashing import compute_file_hash
from execution.tools.tool_registry import Tool, ToolRegistry
from execution.rag.rag_service import init_rag_db
from execution.lodder.logger import setup_logging, get_logger

from paths import INPUT_DIR, OUTPUT_DIR, DIRECTIVES_DIR


# ─── Настройка ────────────────────────────────────────────────

setup_logging()
logger = get_logger("contract_analyzer")

OUTPUT_DIR.mkdir(exist_ok=True)

if not INPUT_DIR.exists():
    raise SystemExit(f"❌ Папка с входными договорами не найдена: {INPUT_DIR}")

if not DIRECTIVES_DIR.exists():
    raise SystemExit(f"❌ Папка с директивами не найдена: {DIRECTIVES_DIR}")

required_directives = [
    "contract_analysis.md",
    "risk_analysis.md",
    "summary_report.md",
]
for name in required_directives:
    if not (DIRECTIVES_DIR / name).exists():
        raise SystemExit(f"❌ Не найден файл директивы: {name}")


# ─── Глобальные сервисы ───────────────────────────────────────

client = anthropic.Anthropic(timeout=60)
langfuse = get_client()
pricing = PricingService()
app.include_router(review_router)

def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def save_file(path: Path, content: str):
    path.write_text(content, encoding="utf-8")


extraction_service = ExtractionService(
    llm=AnthropicLLM(client),
    directive=read_file(DIRECTIVES_DIR / "contract_analysis.md"),
)
analysis_service = AnalysisService(
    llm=AnthropicLLM(client),
    vectors=ChromaStore(),
    directive=read_file(DIRECTIVES_DIR / "risk_analysis.md"),
)


# ─── Summary с retry ──────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
        anthropic.RateLimitError,
        anthropic.InternalServerError,
    )),
    reraise=True,
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def create_summary(contract_json, risk_report, processing_id: int, user_id: int) -> str:
    """
    Финальный summary через Claude Haiku.
    Пишет метрику через LLMCallRepository (в отдельной сессии).
    """
    if hasattr(contract_json, 'model_dump'):
        contract_dict = contract_json.model_dump()
    else:
        contract_dict = contract_json

    directive = read_file(DIRECTIVES_DIR / "summary_report.md")
    start_time = time.time()

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1200,
        messages=[{
            "role": "user",
            "content": f"""
{directive}

JSON договора:
    {json.dumps(contract_dict, ensure_ascii=False, indent=2)}

Risk report:
{risk_report}
"""
        }]
    )

    latency_ms = int((time.time() - start_time) * 1000)
    tokens_in = response.usage.input_tokens
    tokens_out = response.usage.output_tokens
    model = "claude-haiku-4-5"
    cost_usd = pricing.calculate(model, tokens_in, tokens_out)

    # Пишем метрику через репозиторий
    try:
        with SessionLocal() as session:
            LLMCallRepository(session).record(
                processing_id=processing_id,
                model=model,
                stage="summary",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
            )
            session.commit()
    except Exception as e:
        logger.warning(f"Failed to record summary metric: {e}")

    return response.content[0].text


# ─── Обработка одного договора ────────────────────────────────

@observe(name="process_contract")
def process_contract(file_path: Path, user_id: int, notifier_manager):
    """Обрабатывает один договор от начала до конца."""
    logger.info(f"Processing file: {file_path.name}")
    file_hash = compute_file_hash(file_path)

    # Открываем сессию на всю обработку одного файла
    with SessionLocal() as session:
        processing_repo = ProcessingRepository(session)
        counterparty_repo = CounterpartyRepository(session)
        risk_repo = CounterpartyRiskRepository(session)

        # Создаём processing и сразу коммитим
        processing = processing_repo.create(
            file_hash=file_hash,
            filename=file_path.name,
            user_id=user_id,
        )
        processing_id = processing.id
        session.commit()

        logger.info(f"Начинаю обработку: {file_path.name}")

        # Обогащаем trace метаданными
        langfuse.update_current_span(metadata={
            "user_id": str(user_id),
            "filename": file_path.name,
            "processing_id": processing_id,
            "file_hash": file_hash[:16],
        })

        try:
            contract_text = DocumentParser.parse(file_path)
            extracted_data = extraction_service.extract(contract_text, processing_id, user_id)
            logger.info(f"Contract data extracted: {file_path.name}")

            # Memory: контрагенты
            counterparty_context = ""
            for party in extracted_data.parties:
                if party.inn:
                    counterparty_repo.save_or_update(user_id, party.inn, party.name)

                    cp = counterparty_repo.get(user_id, party.inn)
                    if cp and cp.times_seen > 1:
                        past_risks = risk_repo.list_by_counterparty(user_id, party.inn, limit=10)
                        if past_risks:
                            logger.info(f"Контрагент {party.name} встречался {cp.times_seen} раз!")
                            risks_text = "\n".join(
                                f"  - [{r.severity}] {r.risk_text} (договор {r.document_number})"
                                for r in past_risks
                            )
                            counterparty_context += (
                                f"\nКонтрагент {party.name} (ИНН {party.inn}) "
                                f"встречался {cp.times_seen} раз.\n"
                                f"Прошлые риски:\n{risks_text}\n"
                            )

            # Сохраняем extracted JSON
            json_output_path = OUTPUT_DIR / f"{file_path.stem}_extracted.json"
            save_file(json_output_path, extracted_data.model_dump_json(ensure_ascii=False, indent=2))
            logger.info(f"Extracted JSON saved: {json_output_path.name}")

            # Анализ рисков
            risk_report = analysis_service.analyze(
                extracted_data,
                processing_id,
                user_id,
                extra_context=counterparty_context if counterparty_context else None,
            )

            # Сохраняем найденные риски
            for party in extracted_data.parties:
                if party.inn and risk_report.report_md:
                    risk_repo.record(
                        user_id=user_id,
                        counterparty_inn=party.inn,
                        processing_id=processing_id,
                        document_number=extracted_data.document_number or file_path.stem,
                        risk_text=risk_report.report_md[:500],
                        severity=RiskSeverity.MEDIUM,
                    )

            logger.info(f"Risk analysis completed: {file_path.name}")

            # Сохраняем risk report
            risk_output_path = OUTPUT_DIR / f"{file_path.stem}_risk_report.md"
            save_file(risk_output_path, risk_report.report_md)

            # Summary
            summary = create_summary(extracted_data, risk_report, processing_id, user_id)
            summary_output_path = OUTPUT_DIR / f"{file_path.stem}_summary.md"
            save_file(summary_output_path, summary)
            logger.info(f"Summary saved: {summary_output_path.name}")

            processing_repo.mark_success(processing_id, str(summary_output_path))
            session.commit()

            # Доставка (Telegram)
            try:
                delivery_result = notifier_manager.send_primary(
                    text=summary,
                    processing_id=processing_id,
                    primary_channel="telegram",
                )
                logger.info(f"Delivery result: {delivery_result}")
            except Exception as e:
                logger.exception(f"Delivery failed {e}")

            logger.info(f"✅ Готово: {file_path.name}")

        except Exception as e:
            session.rollback()
            processing_repo.mark_failure(processing_id, str(e))
            session.commit()
            logger.exception(f"Failed to process file: {file_path.name}")
            raise  # Langfuse отметит trace как failed


# ─── Основной pipeline ────────────────────────────────────────

def run_pipeline(user_id: int = 1):
    logger.info("Pipeline started")
    init_rag_db()
    ctx = build_context_for_user(user_id)
    
    # for file_path in files:
        # process_contract(ctx, processing_id, file_path, user_id)
    # Загружаем юзера через репозиторий
    with SessionLocal() as session:
        user = UserRepository(session).get_by_id(user_id)
        if not user:
            raise SystemExit(f"❌ User {user_id} не найден в БД.")

        # Копируем нужные поля в dict — сессия закроется, объект User станет detached
        user_data = {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "telegram_chat_id": user.telegram_chat_id,
            "preferred_delivery": user.preferred_delivery,
        }

    logger.info(f"Working as: {user_data['name']} (id={user_data['id']})")
    notifier_manager = build_notifier_for_user(user_data)

    # Регистрируем tools
    registry = ToolRegistry()
    registry.add(Tool(
        name="create_agreement_contract",
        description="Извлекает структурированные поля из текста договора",
        output_schema=AgreementContractOutput,
        handler=None,
    ))
    registry.add(Tool(
        name="retrieve_documents",
        description="Поиск похожих договоров в базе для сравнения рисков",
        output_schema=RetrieveDocumentsInput,
        handler=None,
    ))

    # Собираем файлы
    files = []
    for ext in ["*.txt", "*.pdf", "*.docx"]:
        files.extend(INPUT_DIR.glob(ext))

    if not files:
        logger.warning("No files found in input directory")
        return

    # Обрабатываем каждый
    for file_path in files:
        file_hash = compute_file_hash(file_path)
        # Проверка идемпотентности через отдельную мини-сессию
        with SessionLocal() as check_session:
            already = ProcessingRepository(check_session).exists_completed(file_hash, user_id)

        if already:
            logger.info(f"Пропускаю (уже обработан): {file_path.name}")
            continue

        try:
            process_contract(ctx, file_path, user_id, notifier_manager)
        except Exception:
            continue

    langfuse.flush()
    logger.info("Pipeline finished")


if __name__ == "__main__":
    run_pipeline(user_id=1)