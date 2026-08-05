"""
file_validation.py — валидация входных документов ДО парсинга и анализа.

Отделено от DocumentParser намеренно: парсер парсит, валидатор валидирует.
Валидатор самодостаточен — сам открывает файл для подсчёта страниц и
определения реального типа, ничего не зная о внутренностях парсера.

Две фазы:
  1. validate_input_file(path)      — до парсинга: существование, размер,
                                        реальный MIME vs расширение, число страниц.
  2. validate_extracted_text(text)  — после парсинга: потолок символов.

При провале кидает FileValidationError с человекочитаемым сообщением —
оно уйдёт в processing.mark_failure и вернётся пользователю.
"""
import logging
from pathlib import Path

logger = logging.getLogger("file_validation")

# ─── Лимиты ───────────────────────────────────────────────────
MAX_FILE_SIZE = 20 * 1024 * 1024          # 20 МБ — как в Telegram-боте
MAX_PAGES = 200                            # PDF/DOCX
MAX_EXTRACTED_TEXT_CHARS = 500_000         # потолок текста после извлечения

ALLOWED_SUFFIXES = (".txt", ".pdf", ".docx")

# Реальные MIME, которые допустимы для каждого расширения.
# python-magic читает "магические байты" содержимого, а не доверяет имени файла.
_SUFFIX_TO_MIMES = {
    ".pdf": {"application/pdf"},
    ".docx": {
        # docx — это zip-контейнер; magic обычно отдаёт один из этих
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
    },
    ".txt": {"text/plain"},
}


class FileValidationError(Exception):
    """Валидация входного файла не прошла. Сообщение безопасно показать юзеру."""


# ─── python-magic: мягкая зависимость ─────────────────────────
try:
    import magic  # python-magic (требует системную libmagic)
    _MAGIC_AVAILABLE = True
except Exception:  # ImportError или отсутствие libmagic
    _MAGIC_AVAILABLE = False
    logger.warning(
        "python-magic недоступен — MIME-проверка по содержимому пропускается. "
        "Остальные проверки работают."
    )


# ─── Фаза 1: до парсинга ──────────────────────────────────────

def validate_input_file(file_path: Path) -> None:
    """
    Проверяет файл ДО парсинга. Кидает FileValidationError при любом провале.

    Проверки:
      - файл существует;
      - расширение поддерживается;
      - размер в пределах лимита;
      - реальный тип (MIME по содержимому) совпадает с расширением;
      - число страниц (PDF/DOCX) в пределах лимита.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileValidationError(f"Файл не найден: {file_path.name}")

    suffix = file_path.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise FileValidationError(
            f"Формат {suffix or '(без расширения)'} не поддерживается. "
            f"Нужен .txt, .pdf или .docx."
        )

    # Размер
    size = file_path.stat().st_size
    if size == 0:
        raise FileValidationError("Файл пустой.")
    if size > MAX_FILE_SIZE:
        raise FileValidationError(
            f"Файл слишком большой ({size // (1024*1024)} МБ). "
            f"Лимит {MAX_FILE_SIZE // (1024*1024)} МБ."
        )

    # Реальный MIME по содержимому (защита от переименованного файла)
    _validate_mime(file_path, suffix)

    # Число страниц
    _validate_pages(file_path, suffix)

    logger.info("Файл прошёл валидацию входа: %s (%d байт)", file_path.name, size)


def _validate_mime(file_path: Path, suffix: str) -> None:
    """Сверяет реальный тип содержимого с расширением. Пропускается, если magic нет."""
    if not _MAGIC_AVAILABLE:
        return

    try:
        real_mime = magic.from_file(str(file_path), mime=True)
    except Exception as e:
        logger.warning("Не удалось определить MIME для %s: %s", file_path.name, e)
        return  # не блокируем из-за сбоя самой magic

    allowed = _SUFFIX_TO_MIMES.get(suffix, set())
    # text/plain для .txt проверим отдельной UTF-8 проверкой ниже — здесь мягко
    if real_mime not in allowed:
        # для .txt magic иногда отдаёт application/csv, text/x-* и т.п. — не палимся
        if suffix == ".txt" and real_mime.startswith("text/"):
            return
        raise FileValidationError(
            f"Содержимое файла не соответствует расширению {suffix}. "
            f"Определён тип: {real_mime}. Возможно, файл переименован."
        )


def _validate_pages(file_path: Path, suffix: str) -> None:
    """Считает страницы PDF/DOCX (валидатор сам открывает файл). TXT страниц не имеет."""
    if suffix == ".pdf":
        _validate_pdf_pages(file_path)
    elif suffix == ".docx":
        # У .docx нет жёсткого понятия страниц до рендера — считаем по параграфам
        # как грубый прокси на "бомбу". Абзацев кратно больше, чем страниц.
        _validate_docx_size(file_path)
    # .txt — потолок символов проверится на фазе 2


def _validate_pdf_pages(file_path: Path) -> None:
    try:
        import pdfplumber
    except ImportError:
        logger.warning("pdfplumber нет — пропускаю подсчёт страниц PDF")
        return
    try:
        with pdfplumber.open(file_path) as pdf:
            n_pages = len(pdf.pages)
    except Exception as e:
        raise FileValidationError(f"Не удалось открыть PDF: {e}")

    if n_pages > MAX_PAGES:
        raise FileValidationError(
            f"В PDF слишком много страниц ({n_pages}). Лимит {MAX_PAGES}."
        )


def _validate_docx_size(file_path: Path) -> None:
    try:
        from docx import Document
    except ImportError:
        logger.warning("python-docx нет — пропускаю проверку DOCX")
        return
    try:
        doc = Document(file_path)
        n_paragraphs = len(doc.paragraphs)
    except Exception as e:
        raise FileValidationError(f"Не удалось открыть DOCX: {e}")

    # ~40 абзацев на страницу — грубая верхняя оценка страниц
    approx_pages = n_paragraphs / 40
    if approx_pages > MAX_PAGES:
        raise FileValidationError(
            f"DOCX слишком большой (~{int(approx_pages)} страниц). Лимит {MAX_PAGES}."
        )


# ─── Фаза 2: после парсинга ───────────────────────────────────

def validate_extracted_text(text: str) -> None:
    """
    Проверяет уже извлечённый текст. Кидает FileValidationError при провале.

    - текст не пустой (иначе парсинг фактически ничего не дал);
    - длина в пределах потолка (грубый прокси на бюджет токенов;
      настоящий лимит по токенам — в LLMGateway, отдельно).
    """
    if not text or not text.strip():
        raise FileValidationError(
            "Из документа не извлёкся текст. Возможно, это скан без OCR "
            "или повреждённый файл."
        )

    n = len(text)
    if n > MAX_EXTRACTED_TEXT_CHARS:
        raise FileValidationError(
            f"Документ слишком длинный ({n} символов). "
            f"Лимит {MAX_EXTRACTED_TEXT_CHARS}. "
            f"(chunked-анализ для 100k–500k — TODO, отдельный этап.)"
        )

    logger.info("Извлечённый текст прошёл валидацию: %d символов", n)