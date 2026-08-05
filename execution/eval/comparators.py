"""
Три уровня сравнения полей:
1. Exact — строгое ==
2. Normalized — после нормализации (даты, суммы, текст)
3. Semantic — заглушка для Недели 7-8 (LLM-as-Judge)
"""
from typing import Any, Optional
from .normalizers import normalize_date, normalize_amount, normalize_text, normalize_percent


# Поля по типам — для выбора правильного нормализатора
DATE_FIELDS = {"document_date", "execution_term"}
AMOUNT_FIELDS = {"price_amount"}
PERCENT_FIELDS = {"penalties"}
TEXT_FIELDS = {
    "document_number", "subject", "price", "currency",
    "payment_terms", "delivery_terms", "termination_terms",
    "liability", "acceptance_procedure", "governing_law",
    "dispute_resolution",
}


def compare_exact(actual: Any, expected: Any) -> bool:
    """Строгое сравнение =="""
    if expected is None:
        return actual is None
    if actual is None:
        return False
    return str(actual).strip() == str(expected).strip()


def compare_normalized(actual: Any, expected: Any, field_name: str) -> bool:
    """Сравнение после нормализации"""
    if expected is None:
        return actual is None
    if actual is None:
        return False

    # Даты
    if field_name in DATE_FIELDS:
        norm_a = normalize_date(str(actual))
        norm_e = normalize_date(str(expected))
        if norm_a and norm_e:
            return norm_a == norm_e

    # Суммы
    if field_name in AMOUNT_FIELDS:
        norm_a = normalize_amount(actual)
        norm_e = normalize_amount(expected)
        if norm_a is not None and norm_e is not None:
            return abs(norm_a - norm_e) < 0.01

    # Проценты
    if field_name in PERCENT_FIELDS:
        norm_a = normalize_percent(str(actual))
        norm_e = normalize_percent(str(expected))
        if norm_a and norm_e:
            return norm_a == norm_e

    # Текст — normalize + сравнить
    norm_a = normalize_text(str(actual))
    norm_e = normalize_text(str(expected))
    return norm_a == norm_e


def compare_semantic(actual: Any, expected: Any, field_name: str, llm=None) -> bool:
    """
    Семантическое сравнение через LLM-as-Judge.
    LLM отвечает: "это одно и то же по смыслу? да/нет"
    """
    if expected is None:
        return actual is None
    if actual is None:
        return False

    a = normalize_text(str(actual))
    e = normalize_text(str(expected))

    # Быстрые проверки (без LLM-вызова)
    if a == e:
        return True
    if e in a or a in e:
        return True

    # LLM-as-Judge
    if llm is None:
        # Fallback на старую логику если LLM не передан
        words_a = set(a.split())
        words_e = set(e.split())
        if not words_e:
            return False
        return len(words_a & words_e) / len(words_e) >= 0.6

    try:
        response = llm.client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=10,
            messages=[{
                "role": "user",
                "content": (
                    f"Эти два текста означают одно и то же по смыслу?\n\n"
                    f"Текст A: {a[:200]}\n"
                    f"Текст B: {e[:200]}\n\n"
                    f"Ответь ТОЛЬКО 'да' или 'нет'."
                )
            }]
        )
        answer = response.content[0].text.strip().lower()
        return answer in ("да", "yes", "da")
    except Exception:
        # Fallback при ошибке
        words_a = set(a.split())
        words_e = set(e.split())
        if not words_e:
            return False
        return len(words_a & words_e) / len(words_e) >= 0.6


def compare_parties(actual_parties: list, expected_parties: list, llm=None) -> dict:
    """
    Сравнение сторон (список). Отдельно — потому что это вложенная структура.
    Возвращает: {"exact": X%, "normalized": Y%, "semantic": Z%}
    """
    if not expected_parties:
        return {"exact": 100.0, "normalized": 100.0, "semantic": 100.0}

    # Проверяем количество
    count_match = len(actual_parties) == len(expected_parties)

    if not actual_parties:
        return {"exact": 0.0, "normalized": 0.0, "semantic": 0.0}

    # Попарное сравнение (по порядку)
    party_fields = ["name", "role", "inn", "ogrn", "address",
                    "signatory_name", "signatory_position", "power_basis"]

    total = 0
    exact_ok = 0
    norm_ok = 0
    sem_ok = 0

    for i, exp_party in enumerate(expected_parties):
        if i >= len(actual_parties):
            total += len(party_fields)
            continue

        act_party = actual_parties[i]
        exp_dict = exp_party if isinstance(exp_party, dict) else exp_party.model_dump()
        act_dict = act_party if isinstance(act_party, dict) else act_party.model_dump()

        for field in party_fields:
            exp_val = exp_dict.get(field)
            act_val = act_dict.get(field)

            if exp_val is None:
                continue  # Не проверяем None-поля в golden

            total += 1
            if compare_exact(act_val, exp_val):
                exact_ok += 1
            if compare_normalized(act_val, exp_val, field):
                norm_ok += 1
            if compare_semantic(act_val, exp_val, field, llm=llm):
                sem_ok += 1

    if total == 0:
        return {"exact": 100.0, "normalized": 100.0, "semantic": 100.0}

    return {
        "exact": round(exact_ok / total * 100, 2),
        "normalized": round(norm_ok / total * 100, 2),
        "semantic": round(sem_ok / total * 100, 2),
    }


def compare_fields(actual, expected_output, skip_fields=None, llm=None) -> dict:
    """
    Сравнивает все поля actual vs expected.
    Возвращает детальный отчёт по каждому полю + summary.
    """
    skip = skip_fields or {"parties"}  # parties сравниваем отдельно
    fields_report = {}

    total = 0
    exact_ok = 0
    norm_ok = 0
    sem_ok = 0

    exp_dict = expected_output if isinstance(expected_output, dict) else expected_output.model_dump()
    act_dict = actual if isinstance(actual, dict) else actual.model_dump()

    for field_name, exp_val in exp_dict.items():
        if field_name in skip:
            continue
        if exp_val is None:
            continue  # Не тестируем None-поля

        act_val = act_dict.get(field_name)
        total += 1

        is_exact = compare_exact(act_val, exp_val)
        is_norm = compare_normalized(act_val, exp_val, field_name)
        is_sem = compare_semantic(act_val, exp_val, field_name, llm=llm)

        if is_exact:
            exact_ok += 1
        if is_norm:
            norm_ok += 1
        if is_sem:
            sem_ok += 1

        fields_report[field_name] = {
            "expected": str(exp_val)[:60],
            "actual": str(act_val)[:60],
            "exact": is_exact,
            "normalized": is_norm,
            "semantic": is_sem,
        }

    summary = {
        "total_fields": total,
        "exact": round(exact_ok / total * 100, 2) if total else 0,
        "normalized": round(norm_ok / total * 100, 2) if total else 0,
        "semantic": round(sem_ok / total * 100, 2) if total else 0,
    }

    return {"fields": fields_report, "summary": summary}