"""
Нормализаторы для сравнения полей.
Приводят разные форматы к единому виду.

Примеры:
  "22.04.2025" → "2025-04-22"
  "5 800 000"  → 5800000
  "0,1%"       → "0.1%"
  "  ООО «Тест» " → "ооо тест"
"""
import re
from datetime import datetime
from typing import Optional


def normalize_date(value: str) -> Optional[str]:
    """
    Приводит дату к формату YYYY-MM-DD.
    Поддерживает: DD.MM.YYYY, DD/MM/YYYY, YYYY-MM-DD,
    "22 апреля 2025", "April 22, 2025", "August 30, 2025"
    """
    if not value or not isinstance(value, str):
        return None

    value = value.strip()

    # Уже в формате YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return value

    # DD.MM.YYYY или DD/MM/YYYY
    match = re.match(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})$", value)
    if match:
        d, m, y = match.groups()
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"

    # Русские месяцы
    ru_months = {
        "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
        "мая": 5, "июня": 6, "июля": 7, "августа": 8,
        "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
    }
    for month_name, month_num in ru_months.items():
        pattern = rf"(\d{{1,2}})\s+{month_name}\s+(\d{{4}})"
        match = re.search(pattern, value.lower())
        if match:
            d, y = match.groups()
            return f"{y}-{str(month_num).zfill(2)}-{d.zfill(2)}"

    # English months
    en_months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }
    for month_name, month_num in en_months.items():
        # "August 30, 2025" или "30 August 2025"
        pattern1 = rf"{month_name}\s+(\d{{1,2}}),?\s+(\d{{4}})"
        match = re.search(pattern1, value.lower())
        if match:
            d, y = match.groups()
            return f"{y}-{str(month_num).zfill(2)}-{d.zfill(2)}"

        pattern2 = rf"(\d{{1,2}})\s+{month_name}\s+(\d{{4}})"
        match = re.search(pattern2, value.lower())
        if match:
            d, y = match.groups()
            return f"{y}-{str(month_num).zfill(2)}-{d.zfill(2)}"

    return value  # не удалось нормализовать


def normalize_amount(value) -> Optional[float]:
    """
    Приводит сумму к числу.
    "5 800 000" → 5800000.0
    "12 450 000 рублей без НДС" → 12450000.0
    "USD 145,000" → 145000.0
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    s = str(value)
    # Убираем всё кроме цифр, точек, запятых
    # Сначала убираем текст (рублей, без НДС, USD итд)
    cleaned = re.sub(r"[^\d.,\s]", "", s)
    # Убираем пробелы (разделитель тысяч)
    cleaned = cleaned.replace(" ", "")
    # Запятая как разделитель тысяч (1,250,000) или десятичная (1,5)
    if "," in cleaned and "." not in cleaned:
        # Если формат 1,250,000 — убираем запятые
        if re.match(r"^\d{1,3}(,\d{3})+$", cleaned):
            cleaned = cleaned.replace(",", "")
        else:
            # Это десятичная запятая
            cleaned = cleaned.replace(",", ".")
    elif "," in cleaned and "." in cleaned:
        # 1,250.00 — запятая это тысячи
        cleaned = cleaned.replace(",", "")

    try:
        return float(cleaned)
    except ValueError:
        return None


def normalize_text(value: str) -> str:
    """
    Нормализует текст для сравнения:
    - lowercase
    - убирает лишние пробелы
    - убирает кавычки «»""
    - убирает знаки препинания в конце
    """
    if not value or not isinstance(value, str):
        return ""

    s = value.strip().lower()
    # Убираем кавычки
    s = re.sub(r"[«»\"'""„]", "", s)
    # Убираем точки/запятые в конце
    s = re.sub(r"[.,;:!]+$", "", s)
    # Нормализуем пробелы
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def normalize_percent(value: str) -> Optional[str]:
    """
    Нормализует проценты: "0,1%" → "0.1%", "0.05 %" → "0.05%"
    """
    if not value or not isinstance(value, str):
        return None

    match = re.search(r"(\d+[.,]?\d*)\s*%", value)
    if match:
        num = match.group(1).replace(",", ".")
        return f"{num}%"
    return None