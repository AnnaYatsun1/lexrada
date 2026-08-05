from enum import Enum, StrEnum
from typing import Literal
import json
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Recommendation(str, Enum):
    SIGN = "SIGN"
    NEEDS_REVISION = "NEEDS_REVISION"
    DO_NOT_SIGN = "DO_NOT_SIGN"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ─── Категории рисков ─────────────────────────────────────────

class RiskCategory(StrEnum):
    PARTIES_AND_AUTHORITY = "parties_and_authority"
    SUBJECT_AND_SCOPE = "subject_and_scope"
    PRICE_AND_PAYMENT = "price_and_payment"
    PERFORMANCE_AND_DELIVERY = "performance_and_delivery"
    ACCEPTANCE_AND_QUALITY = "acceptance_and_quality"
    LIABILITY_AND_PENALTIES = "liability_and_penalties"
    WARRANTIES_AND_INDEMNITIES = "warranties_and_indemnities"
    TERM_AND_TERMINATION = "term_and_termination"
    CONFIDENTIALITY_AND_DATA_PROTECTION = "confidentiality_and_data_protection"
    INTELLECTUAL_PROPERTY = "intellectual_property"
    COMPLIANCE_AND_REGULATORY = "compliance_and_regulatory"
    DISPUTE_RESOLUTION_AND_JURISDICTION = "dispute_resolution_and_jurisdiction"
    FORCE_MAJEURE_AND_CHANGE = "force_majeure_and_change"
    ASSIGNMENT_AND_SUBCONTRACTING = "assignment_and_subcontracting"
    EXCLUSIVITY_AND_RESTRICTIONS = "exclusivity_and_restrictions"
    DOCUMENT_INTEGRITY = "document_integrity"
    COUNTERPARTY = "counterparty"
    OTHER = "other"


# ─── Доказательства (evidence) ────────────────────────────────

class ClauseEvidence(BaseModel):
    """Обоснование риска — привязка к тексту исходного документа.

    Валидация «quote реально есть в документе» делается ОТДЕЛЬНЫМ
    Python-валидатором (Этап 4), не в схеме: LLM редко цитирует дословно,
    строгая проверка в модели ронял бы легитимные риски.
    """
    quote: str = Field(
        description="Дословная цитата из документа, обосновывающая риск",
        max_length=1000,
    )
    section: str | None = Field(
        None, description="Раздел/пункт договора, откуда цитата (если определим)"
    )
    start_offset: int | None = Field(
        None, description="Смещение начала цитаты в тексте (если известно)"
    )
    end_offset: int | None = Field(
        None, description="Смещение конца цитаты в тексте (если известно)"
    )


# ─── Сигнал prompt injection ──────────────────────────────────

class PromptInjectionSignal(BaseModel):
    """Отметка, что в документе замечен текст, похожий на попытку
    манипуляции автоматическим анализом.

    ВАЖНО: suspected=False НЕ доказывает безопасность. Это сигнал для
    логов и human review, а не гарантия.
    """
    suspected: bool = Field(
        default=False,
        description="True, если в документе есть текст, похожий на инъекцию инструкций",
    )
    evidence: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Фрагменты документа, похожие на инъекцию (для логов/review)",
    )


# ─── Риск ─────────────────────────────────────────────────────

class Risk(BaseModel):
    """Один найденный риск.

    Обратная совместимость: type/severity/text остаются. category и evidence
    добавлены с дефолтами, чтобы не ломать текущий tool-schema и прогон.
    """
    type: str = Field(description="Краткий тип риска (человекочитаемый)")
    severity: Severity
    text: str = Field(description="Описание риска")

    category: RiskCategory = Field(
        default=RiskCategory.OTHER,
        description="Категория риска из фиксированного набора",
    )
    evidence: list[ClauseEvidence] = Field(
        default_factory=list,
        description="Обоснования риска цитатами из документа",
    )


# ─── Типизированное состояние между агентами (Этап 3) ─────────

class RiskFinding(BaseModel):
    """Типизированная единица, которую агенты передают друг другу ВМЕСТО
    свободного текста. Защищает от agent-to-agent prompt injection:
    FinalReviewer принимает структуру, а не произвольную строку от RiskAgent.

    Вводится на Этапе 3 (перевод _refine/_generate_report на структуру).
    Пока определён, но ещё не подключён в пайплайн.
    """
    category: RiskCategory
    severity: Severity
    clause_text: str = Field(max_length=2000)
    explanation: str = Field(max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[ClauseEvidence] = Field(default_factory=list)

class RiskEvidenceDraft(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    quote: str = Field(min_length=1, max_length=3_000)
    section: str | None = Field(default=None, max_length=200)

class RiskFindingDraft(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    category: RiskCategory
    severity: Severity
    title: str = Field(min_length=3, max_length=200)
    explanation: str = Field(min_length=10, max_length=2_000)
    recommendation: str = Field(min_length=5, max_length=1_000)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[RiskEvidenceDraft] = Field(default_factory=list, max_length=10)

class RiskAnalysisDraft(BaseModel):
    risk_level: RiskLevel
    score: int = Field(ge=1, le=10)

    risks: list[Risk] = Field(default_factory=list)
    findings: list[RiskFindingDraft] = Field(default_factory=list)

    recommendation: Recommendation = Recommendation.NEEDS_REVISION

    security: PromptInjectionSignal = Field(
        default_factory=PromptInjectionSignal,
        description=(
            "Сигнал о подозрении на prompt injection "
            "в документе"
        ),
    )

    @field_validator("risks", "findings", mode="before")
    @classmethod
    def _parse_stringified_lists(cls, value):
        if not isinstance(value, str):
            return value

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Expected a list or a JSON-encoded list"
            ) from exc

        if not isinstance(parsed, list):
            raise ValueError(
                "Decoded JSON value must be a list"
            )

        return parsed


class RiskAnalysis(RiskAnalysisDraft):
    """Draft + наш текст. Финальный объект анализа."""
    report_md: str


# ─── Критика (без изменений) ──────────────────────────────────

class CritiqueResult(BaseModel):
    status: Literal["ok", "needs_revision"] = Field(
        description="Общий вердикт: ok если отчёт полный, needs_revision если есть проблемы"
    )
    missed_checks: list[str] = Field(
        default_factory=list,
        description="Пункты договора которые не проверены на соответствие закону",
    )
    hallucinations: list[str] = Field(
        default_factory=list,
        description="Утверждения со ссылками на статьи которых нет в retrieved контексте",
    )
    weak_claims: list[str] = Field(
        default_factory=list,
        description="Выводы без ссылки на конкретную норму права",
    )
    additional_queries: list[str] = Field(
        default_factory=list,
        description="повторный поиск законов после критики",
    )



# ─── Источник finding'а ───
class FindingSource(StrEnum):
    RISK_AGENT = "risk_agent"
    COMPLIANCE_AGENT = "compliance_agent"
    FINAL_REVIEWER = "final_reviewer"
    COUNTERPARTY_DATABASE = "counterparty_database"
    SYSTEM_VALIDATOR = "system_validator"


# ─── Статусы верификации цитаты ───
class EvidenceMatchStatus(StrEnum):
    EXACT = "exact"
    NORMALIZED = "normalized"
    UNVERIFIED = "unverified"


class FindingEvidenceStatus(StrEnum):
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    UNVERIFIED = "unverified"
    MISSING = "missing"


# ─── Draft-модели (заполняет LLM) ───





class RiskAgentDraft(BaseModel):
    """Что заполняет RiskAgent через tool. extra='ignore' — болтливость модели
    не роняет. findings — типизированные, вместо старого list[Risk]."""
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    risk_level: RiskLevel
    score: int = Field(ge=1, le=10)
    recommendation: Recommendation = Recommendation.NEEDS_REVISION
    findings: list[RiskFindingDraft] = Field(default_factory=list)

    @field_validator("findings", mode="before")
    @classmethod
    def _parse_stringified_findings(cls, value):
        if not isinstance(value, str):
            return value

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "findings contains invalid JSON"
            ) from exc

        if not isinstance(parsed, list):
            raise ValueError(
                "findings JSON must contain a list"
            )

        return parsed

class RiskEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    quote: str = Field(min_length=1, max_length=3_000)
    section: str | None = Field(default=None, max_length=200)
    match_status: EvidenceMatchStatus = EvidenceMatchStatus.UNVERIFIED


class RiskFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    category: RiskCategory
    severity: Severity
    title: str = Field(min_length=3, max_length=200)
    explanation: str = Field(min_length=10, max_length=2_000)
    recommendation: str = Field(min_length=5, max_length=1_000)
    confidence: float = Field(ge=0.0, le=1.0)
    source: FindingSource
    evidence: list[RiskEvidence] = Field(default_factory=list, max_length=10)
    evidence_status: FindingEvidenceStatus = FindingEvidenceStatus.MISSING


def _match_quote(quote: str, document_text: str) -> EvidenceMatchStatus:
    if quote in document_text:
        return EvidenceMatchStatus.EXACT
    return EvidenceMatchStatus.UNVERIFIED


def _aggregate_status(evidence: list[RiskEvidence]) -> FindingEvidenceStatus:
    if not evidence:
        return FindingEvidenceStatus.MISSING
    verified = [
        e for e in evidence
        if e.match_status in (EvidenceMatchStatus.EXACT, EvidenceMatchStatus.NORMALIZED)
    ]
    if len(verified) == len(evidence):
        return FindingEvidenceStatus.VERIFIED
    if verified:
        return FindingEvidenceStatus.PARTIALLY_VERIFIED
    return FindingEvidenceStatus.UNVERIFIED


def finalize_finding(
    draft: RiskFindingDraft,
    document_text: str,
    source: FindingSource,
) -> RiskFinding:
    verified_evidence = [
        RiskEvidence(
            quote=ev.quote,
            section=ev.section,
            match_status=_match_quote(ev.quote, document_text),
        )
        for ev in draft.evidence
    ]
    return RiskFinding(
        category=draft.category,
        severity=draft.severity,
        title=draft.title,
        explanation=draft.explanation,
        recommendation=draft.recommendation,
        confidence=draft.confidence,
        source=source,
        evidence=verified_evidence,
        evidence_status=_aggregate_status(verified_evidence),
    )