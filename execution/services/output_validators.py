"""
output_validators.py — валидаторы выхода анализа (Этап 4).

Принцип: НЕ роняем пайплайн и НЕ удаляем findings. Накапливаем проблемы
в список issues и сигналим requires_manual_review=True. Договор всё равно
сохраняется — решение принимает человек на review.

Два валидатора:
  1. verify_findings_evidence — сверяет цитаты findings с тем, что видел агент
     (json.dumps(contract_dict)), проставляет match_status / evidence_status.
  2. check_score_consistency — сверяет score с risk_level по диапазонам.
"""
import logging
from dataclasses import dataclass, field

from execution.models.analysis import (
    RiskLevel,
    FindingEvidenceStatus,
    EvidenceMatchStatus,
    Severity,
)

logger = logging.getLogger("output_validators")


@dataclass
class ValidationResult:
    """Результат проверки выхода. Не роняет — накапливает."""
    issues: list[str] = field(default_factory=list)
    requires_manual_review: bool = False

    def add(self, issue: str) -> None:
        self.issues.append(issue)
        self.requires_manual_review = True


# ─── Score ↔ risk_level ───────────────────────────────────────
# Прямая шкала: 1 = минимальный риск, 10 = максимальный.

def expected_level_for_score(score: int) -> RiskLevel:
    if score <= 3:
        return RiskLevel.LOW
    if score <= 6:
        return RiskLevel.MEDIUM
    return RiskLevel.HIGH


def check_score_consistency(risk_level: RiskLevel, score: int) -> str | None:
    """Возвращает текст проблемы, если score не соответствует risk_level. Иначе None."""
    expected = expected_level_for_score(score)
    # сравниваем по имени, т.к. risk_level может прийти строкой или enum
    actual = getattr(risk_level, "value", risk_level)
    expected_val = expected.value
    if str(actual).upper() != expected_val:
        return (
            f"score={score} ожидает уровень {expected_val}, "
            f"но выставлен {actual}"
        )
    return None


# ─── Evidence-верификация ─────────────────────────────────────

def _match_quote(quote: str, document: str) -> EvidenceMatchStatus:
    """Пока только точное вхождение. NORMALIZED — на вырост (fuzzy)."""
    if quote and quote in document:
        return EvidenceMatchStatus.EXACT
    return EvidenceMatchStatus.UNVERIFIED


def _aggregate(statuses: list[EvidenceMatchStatus]) -> FindingEvidenceStatus:
    if not statuses:
        return FindingEvidenceStatus.MISSING
    verified = [
        s for s in statuses
        if s in (EvidenceMatchStatus.EXACT, EvidenceMatchStatus.NORMALIZED)
    ]
    if len(verified) == len(statuses):
        return FindingEvidenceStatus.VERIFIED
    if verified:
        return FindingEvidenceStatus.PARTIALLY_VERIFIED
    return FindingEvidenceStatus.UNVERIFIED


def verify_findings_evidence(findings: list, document: str, result: ValidationResult) -> None:
    """
    Прогоняет findings через сверку цитат с document (то, что видел агент —
    json.dumps(contract_dict)). Проставляет статусы, НЕ удаляет findings.

    Правило эскалации: HIGH-риск без единой подтверждённой цитаты → review.
    (severity — enum Severity: low/medium/high; сравниваем по value.)

    findings — список объектов с .severity, .evidence[.quote, .match_status],
    .evidence_status, .title. Мутирует их match_status/evidence_status на месте.
    """
    for f in findings:
        statuses = []
        for ev in f.evidence:
            status = _match_quote(ev.quote, document)
            # проставляем статус цитате (если модель поля допускает мутацию)
            try:
                ev.match_status = status
            except Exception:
                pass
            statuses.append(status)

        agg = _aggregate(statuses)
        try:
            f.evidence_status = agg
        except Exception:
            pass

        severity = getattr(f.severity, "value", f.severity)
        title = getattr(f, "title", "?")

        # HIGH-риск обязан иметь хотя бы одну подтверждённую цитату
        if str(severity).lower() == "high" and agg in (
            FindingEvidenceStatus.UNVERIFIED,
            FindingEvidenceStatus.MISSING,
        ):
            result.add(
                f"HIGH-риск '{title}' без подтверждённой цитаты "
                f"(evidence_status={agg.value})"
            )


# ─── Общая точка входа ────────────────────────────────────────

def validate_analysis_output(risk_report, contract_document: str) -> ValidationResult:
    """
    Единая проверка результата анализа. Не роняет, накапливает issues.

    Args:
        risk_report: RiskAnalysis с .risk_level, .score, .findings
        contract_document: то, что видел агент — json.dumps(contract_dict)
    """
    result = ValidationResult()

    # 1. Evidence-верификация findings
    findings = getattr(risk_report, "findings", []) or []
    verify_findings_evidence(findings, contract_document, result)

    # 2. Score ↔ risk_level
    issue = check_score_consistency(risk_report.risk_level, risk_report.score)
    if issue:
        result.add(issue)

    if result.issues:
        logger.warning(
            "Output validation: %d issue(s), manual_review=%s: %s",
            len(result.issues), result.requires_manual_review, result.issues,
        )

    return result