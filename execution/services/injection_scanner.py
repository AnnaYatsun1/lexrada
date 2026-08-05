"""
injection_scanner.py — эвристический детектор prompt injection в тексте документа.

НЕ блокирует обработку. Работает как СИГНАЛИЗАТОР: находит в тексте паттерны,
похожие на попытку манипуляции автоматическим анализом, и возвращает результат.
Решение (поднять risk_level, эскалировать на human review, уведомить юзера)
принимает оркестратор — не этот модуль.

Важно: отсутствие срабатывания НЕ доказывает безопасность. Это лишь сигнал
для логов и ревью. Настоящая защита — изоляция контента (обёртка untrusted +
инструкция-иммунитет в директиве), которая работает всегда и независимо от
этого детектора.

Осознанные ограничения эвристики:
  - ловит известные паттерны, не «понимает» смысл;
  - возможны ложные срабатывания (договор может законно содержать слово
    "инструкция") — поэтому НЕ блокируем, а помечаем;
  - обходится обфускацией — поэтому это лишь один слой из нескольких.
"""
import re
from dataclasses import dataclass, field


def strip_boundary_markers(text: str) -> str:
    """Убирает теги-границы из недоверенного текста, чтобы инъекция не могла
    'закрыть' обёртку и выйти наружу. Чистит и <untrusted_*>, и <agent_output>."""
    return re.sub(r"</?(untrusted_[a-z_]*|agent_output[^>]*)>", "", text, flags=re.IGNORECASE)

# Паттерны-индикаторы инъекций. RU / UK / EN — под твой домен (укр. договоры,
# русскоязычные, плюс англоязычные вставки атак).
# Каждый паттерн — (regex, короткая метка для лога).
_PATTERNS: list[tuple[str, str]] = [
    # Классические англоязычные инъекции
    (r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", "ignore_previous_instructions"),
    (r"disregard\s+(all\s+)?(previous|prior|above)", "disregard_previous"),
    (r"forget\s+(all\s+)?(previous|prior|your)\s+(instructions|rules)", "forget_instructions"),
    (r"you\s+are\s+now\s+", "you_are_now"),
    (r"(reveal|show|print|repeat)\s+(your\s+)?(system\s+prompt|instructions)", "reveal_system_prompt"),
    (r"debug\s+mode", "debug_mode"),
    (r"developer\s+mode", "developer_mode"),
    (r"do\s+not\s+(tell|inform|mention)\s+(the\s+)?(user|anyone)", "do_not_tell_user"),
    (r"without\s+any\s+restrictions", "without_restrictions"),
    (r"act\s+as\s+(if|though|a)\b", "act_as"),
    (r"new\s+instructions?\s*:", "new_instructions"),
    (r"system\s*:\s*", "system_role_injection"),
    (r"</?(system|instructions?|prompt)>", "fake_tags"),

    # Русскоязычные
    (r"игнорир\w*\s+(все\s+)?(предыдущ|вышеуказан|прежн)", "ru_ignore_previous"),
    (r"забуд\w*\s+(все\s+)?(предыдущ|инструкц|правил)", "ru_forget"),
    (r"(покажи|раскрой|выведи|повтори)\s+(свой\s+)?(системн\w+\s+промпт|инструкц)", "ru_reveal_prompt"),
    (r"режим\s+отладки", "ru_debug_mode"),
    (r"без\s+(каких-либо\s+)?ограничени", "ru_without_restrictions"),
    (r"не\s+сообщай\s+(пользовател|никому)", "ru_do_not_tell"),
    (r"ты\s+теперь\s+", "ru_you_are_now"),
    (r"новые\s+инструкци\w*\s*:", "ru_new_instructions"),
    (r"оцени\s+(этот\s+)?договор\s+как\s+(безопасн|безрисков|low)", "ru_force_verdict"),

    # Украинские
    (r"ігнору\w*\s+(всі\s+)?(попередн|вищезазначен)", "uk_ignore_previous"),
    (r"забудь\s+(всі\s+)?(попередн|інструкц|правил)", "uk_forget"),
    (r"(покажи|розкрий|виведи)\s+(свій\s+)?(системн\w+\s+промпт|інструкц)", "uk_reveal_prompt"),
    (r"режим\s+налагодження", "uk_debug_mode"),
    (r"без\s+(будь-яких\s+)?обмежень", "uk_without_restrictions"),
    (r"не\s+повідомляй\s+(користувач|нікому)", "uk_do_not_tell"),
    (r"ти\s+тепер\s+", "uk_you_are_now"),
    (r"оціни\s+(цей\s+)?договір\s+як\s+(безпечн|безризиков|low)", "uk_force_verdict"),
]

_COMPILED = [(re.compile(p, re.IGNORECASE), label) for p, label in _PATTERNS]

# Сколько символов контекста вокруг совпадения сохранять для лога/ревью
_CONTEXT_CHARS = 80
# Максимум фрагментов-улик в результате (совпадает с PromptInjectionSignal.evidence max_length)
_MAX_EVIDENCE = 10


@dataclass
class InjectionScanResult:
    suspected: bool = False
    labels: list[str] = field(default_factory=list)      # какие паттерны сработали
    evidence: list[str] = field(default_factory=list)    # фрагменты текста для лога/ревью


def scan_for_injection(text: str) -> InjectionScanResult:
    """
    Сканирует текст на паттерны prompt injection.

    НЕ блокирует, НE кидает исключений — только возвращает результат.
    Пустой/короткий текст → suspected=False.
    """
    result = InjectionScanResult()
    if not text:
        return result

    seen_labels: set[str] = set()

    for pattern, label in _COMPILED:
        match = pattern.search(text)
        if not match:
            continue

        seen_labels.add(label)

        if len(result.evidence) < _MAX_EVIDENCE:
            start = max(0, match.start() - _CONTEXT_CHARS)
            end = min(len(text), match.end() + _CONTEXT_CHARS)
            snippet = text[start:end].replace("\n", " ").strip()
            result.evidence.append(f"[{label}] …{snippet}…")

    if seen_labels:
        result.suspected = True
        result.labels = sorted(seen_labels)

    return result