"""Бизнес-логика обработки одного договора."""
"""Бизнес-логика обработки одного договора."""

import json
import os
from pathlib import Path
import tempfile

from langfuse import get_client, observe

from execution.database.session import SessionLocal
from execution.lodder.logger import get_logger
from execution.models.analysis import (
    PromptInjectionSignal,
    RiskAnalysis,
)
from execution.orchestration.context import WorkerContext
from execution.repositories.counterparty import (
    CounterpartyRepository,
)
from execution.repositories.counterparty_risk import (
    CounterpartyRiskRepository,
    RiskSeverity,
)
from execution.repositories.processings import (
    ProcessingRepository,
)
from execution.services.classifier import (
    DocumentClassifier,
    DocumentParser,
    get_rag_filter,
)
from execution.services.file_validation import (
    FileValidationError,
    validate_extracted_text,
    validate_input_file,
)
from execution.services.injection_scanner import (
    scan_for_injection,
)
from execution.services.output_validators import (
    validate_analysis_output,
)
from execution.services.storage import StorageService
from paths import OUTPUT_DIR


logger = get_logger("orchestration")
langfuse = get_client()

@observe(name="process_contract")
def process_contract(
    ctx: WorkerContext,
    processing_id: int,
    filename: str,
    user_id: int,
) -> None:
    """
    Обрабатывает один договор от начала до конца.

    Вызывается из:
    - main.py (CLI)
    - tasks/analyze.py (Celery)
    """

    # logger.info("Processing file: %s", file_path.name)

    with SessionLocal() as session:
        processing_repo = ProcessingRepository(session)
        counterparty_repo = CounterpartyRepository(session)
        risk_repo = CounterpartyRiskRepository(session)

        langfuse.update_current_span(
            metadata={
                "user_id": str(user_id),
                "filename": filename,
                "processing_id": processing_id,
            }
        )

        notification_text: str
        notification_channel = "telegram"
        tmp_path: Path | None = None
        try:
        # достаём содержимое из БД (web сохранил туда)
            storage = StorageService(session)
            content = storage.read_file(processing_id)  # bytes из processings.file_content

            # пишем во временный файл на диске worker'а — для парсинга
            suffix = Path(filename).suffix
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)
            try:
                validate_input_file(tmp_path)
                contract_text = DocumentParser.parse(tmp_path)
                validate_extracted_text(contract_text)

                injection_result = scan_for_injection(contract_text)
                if injection_result.suspected:
                    logger.warning(
                        "Injection suspected in %s: labels=%s",
                        filename, injection_result.labels,
                    )
                injection_signal = PromptInjectionSignal(
                    suspected=injection_result.suspected,
                    evidence=injection_result.evidence,
                )
                doc_type, type_name = DocumentClassifier.classify(
                    contract_text,
                    ctx.llm,
                )
                logger.info("Document type: %s", type_name)

                rag_filter = get_rag_filter(
                    doc_type,
                    country="UA",
                )
                logger.info("RAG filter: %s", rag_filter)

                extracted = ctx.extraction_service.extract(
                    contract_text,
                    processing_id,
                    user_id,
                )
                logger.info(
                    "Contract data extracted: %s",
                    filename,
                )

                counterparty_context = ""

                for party in extracted.parties:
                    if not party.inn:
                        continue

                    counterparty_repo.save_or_update(
                        user_id,
                        party.inn,
                        party.name,
                    )

                    counterparty = counterparty_repo.get(
                        user_id,
                        party.inn,
                    )

                    if not counterparty or counterparty.times_seen <= 1:
                        continue

                    past_risks = risk_repo.list_by_counterparty(
                        user_id,
                        party.inn,
                        limit=10,
                    )

                    if not past_risks:
                        continue

                    risks_text = "\n".join(
                        f"- [{risk.severity}] "
                        f"{risk.risk_text[:100]}"
                        for risk in past_risks
                    )

                    counterparty_context += (
                        f"\nКонтрагент {party.name} "
                        f"встречался {counterparty.times_seen} раз.\n"
                        f"Прошлые риски:\n{risks_text}\n"
                    )

                risk_report = ctx.orchestrator.analyze(
                    contract_json=extracted,
                    processing_id=processing_id,
                    user_id=user_id,
                    rag_filter=rag_filter,
                    extra_context=counterparty_context or None,
                )

                risk_report = merge_security_signal(
                    risk_report,
                    injection_signal,
                )

                runtime_issues: list[str] = []

                if risk_report.report_md:
                    report_md = risk_report.report_md
                else:
                    report_md = (
                        "# Частичный результат анализа\n\n"
                        "Текстовый отчёт не был сформирован моделью. "
                        "Структурированные данные сохранены и "
                        "направлены на ручную проверку."
                    )
                    runtime_issues.append(
                        "Модель не сформировала текстовый отчёт."
                    )

                contract_document = json.dumps(
                    extracted.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                )

                validation = validate_analysis_output(
                    risk_report,
                    contract_document,
                )

                all_issues = [
                    *runtime_issues,
                    *[
                        getattr(issue, "message", str(issue))
                        for issue in validation.issues
                    ],
                ]

                # Security-сигнал тоже должен быть виден в Markdown-отчёте.
                if risk_report.security.suspected:
                    all_issues.append(
                        "В документе обнаружен текст, похожий на попытку "
                        "повлиять на автоматический анализ."
                    )

                if all_issues:
                    logger.warning(
                        "Output validation issues "
                        "(processing %s): %s",
                        processing_id,
                        all_issues,
                    )

                    report_md += "\n".join(
                        [
                            "",
                            "",
                            "## Результаты автоматической проверки",
                            "",
                            "Отчёт направлен на ручную проверку.",
                            "",
                            *[
                                f"{index}. {issue}"
                                for index, issue in enumerate(
                                    all_issues,
                                    start=1,
                                )
                            ],
                        ]
                    )

                # Сохраняем уже итоговую версию отчёта и в объекте.
                risk_report = risk_report.model_copy(
                    update={"report_md": report_md}
                )

                report_path = (
                    Path(OUTPUT_DIR)
                    / f"processing_{processing_id}_risk_report.md"
                )

                report_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                report_path.write_text(
                    report_md,
                    encoding="utf-8",
                )

                # Сохраняем историю рисков контрагентов.
                for party in extracted.parties:
                    if not party.inn:
                        continue

                    risk_repo.record(
                        user_id=user_id,
                        counterparty_inn=party.inn,
                        processing_id=processing_id,
                        document_number=(
                            extracted.document_number
                            or Path(filename).stem
                        ),
                        risk_text=report_md[:500],
                        severity=_map_risk_severity(
                            risk_report.risk_level
                        ),
                    )

                risk_level = _risk_level_value(
                    risk_report.risk_level
                )

                requires_human_review = (
                    risk_report.score >= 7
                    or risk_level == "HIGH"
                    or risk_report.security.suspected
                    or validation.requires_manual_review
                    or bool(all_issues)
                )

                issues_text = "\n".join(
                    f"• {issue}"
                    for issue in all_issues
                )

                # На период миграции считаем новый findings,
                # а если он пустой — используем старый risks.
                findings = getattr(risk_report, "findings", [])
                risk_count = (
                    len(findings)
                    if findings
                    else len(risk_report.risks)
                )

                if requires_human_review:
                    processing_repo.mark_pending_review(
                        processing_id=processing_id,
                        result_path=str(report_path),
                    )

                    notification_text = (
                        "⚠️ Новый договор ожидает проверки.\n\n"
                        f"Файл: {filename}\n"
                        f"Score: {risk_report.score}/10\n"
                        f"Уровень риска: {risk_level}\n"
                        f"Количество рисков: {risk_count}\n\n"
                        f"Рекомендация:\n"
                        f"{risk_report.recommendation.value}"
                    )

                    if issues_text:
                        notification_text += (
                            "\n\n🔍 Автоматическая проверка выявила:\n"
                            f"{issues_text}"
                        )

                    logger.info(
                        "Processing %s moved to pending review",
                        processing_id,
                    )

                else:
                    processing_repo.mark_success(
                        processing_id=processing_id,
                        result_path=str(report_path),
                    )

                    notification_text = report_md

                    logger.info(
                        "Processing %s completed without review",
                        processing_id,
                    )
                session.commit()
            except FileValidationError as error:
                session.rollback()

                processing_repo.mark_failure(
                    processing_id,
                    str(error),
                )
                session.commit()

                logger.info(
                    "Файл отклонён валидацией: %s — %s",
                    filename,
                    error,
                )

                _notify_user_error(
                    ctx,
                    processing_id,
                    str(error),
                )

                return
            except Exception as error:
                session.rollback()

                processing_repo.mark_failure(
                    processing_id,
                    str(error),
                )
                session.commit()

                logger.exception(
                    "Failed to process: %s",
                    filename,
                )
                _notify_user_error(
                    ctx, processing_id,
                    "внутренняя ошибка обработки, попробуйте позже",
                )
                raise

            # Ошибка доставки не должна менять успешный AI-статус на failed.
            try:
                ctx.notifier_manager.send_primary(
                    text=notification_text,
                    processing_id=processing_id,
                    primary_channel=notification_channel,
                )

                processing_repo.record_delivery_attempt(
                    processing_id=processing_id,
                    channel=notification_channel,
                    success=True,
                )
                session.commit()

            except Exception as delivery_error:
                session.rollback()

                logger.exception(
                    "Delivery failed for processing %s: %s",
                    processing_id,
                    delivery_error,
                )

                try:
                    processing_repo.record_delivery_attempt(
                        processing_id=processing_id,
                        channel=notification_channel,
                        success=False,
                        error_message=str(delivery_error),
                    )
                    session.commit()

                except Exception:
                    session.rollback()
                    logger.exception(
                        "Could not save delivery failure "
                        "for processing %s",
                        processing_id,
                    )
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

        logger.info("✅ Готово: %s", filename)


def _risk_level_value(risk_level: object) -> str:
    value = getattr(risk_level, "value", risk_level)
    return str(value).upper()


def _map_risk_severity(risk_level: object) -> RiskSeverity:
    value = _risk_level_value(risk_level)

    mapping = {
        "LOW": RiskSeverity.LOW,
        "MEDIUM": RiskSeverity.MEDIUM,
        "HIGH": RiskSeverity.HIGH,
        "CRITICAL": RiskSeverity.HIGH,
    }

    return mapping.get(value, RiskSeverity.MEDIUM)
def merge_security_signal(
    risk_report: RiskAnalysis,
    injection: PromptInjectionSignal,
) -> RiskAnalysis:
    model_security = risk_report.security
    evidence = list(dict.fromkeys([*model_security.evidence, *injection.evidence]))
    merged_security = PromptInjectionSignal(
        suspected=model_security.suspected or injection.suspected,
        evidence=evidence,
    )
    result_data = risk_report.model_dump()
    result_data["security"] = merged_security.model_dump()
    return RiskAnalysis.model_validate(result_data)

def _notify_user_error(ctx, processing_id: int, message: str) -> None:
    """Уведомляет юзера о том, что документ не обработан.

    Своя изолированная обёртка: сбой доставки не должен ронять обработку
    ошибки (иначе получим исключение внутри except). Ничего не re-raise'ит.
    """
    try:
        ctx.notifier_manager.send_primary(
            text=f"❌ Документ не обработан.\nПричина: {message}",
            processing_id=processing_id,
            primary_channel="telegram",
        )
    except Exception:
        logger.exception(
            "Не смог доставить сообщение об ошибке юзеру (processing %s)",
            processing_id,
        )