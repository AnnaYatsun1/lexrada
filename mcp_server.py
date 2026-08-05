"""
mcp_server.py — MCP-сервер LexRadar.

Выставляет накопленную юридическую память (контрагенты, риски, анализы,
справочную базу legal_docs) как MCP-инструменты для LLM-клиентов
(MCP Inspector сейчас, Claude Desktop / Cursor позже).

Запуск локально (stdio):
    python mcp_server.py

Отладка через Inspector:
    fastmcp dev mcp_server.py

Аутентификация: как и REST API, резолвим пользователя по API-ключу
(MCP_API_KEY в окружении), а не по внутреннему id.
"""
import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from execution.database.session import get_session
from execution.repositories.users import UserRepository
from execution.repositories.counterparty import CounterpartyRepository
from execution.repositories.counterparty_risk import CounterpartyRiskRepository
from execution.repositories.processings import ProcessingRepository, ProcessingStatus
from execution.gateways.vectors import ChromaStore
from execution.services.storage import StorageService

load_dotenv()

MAX_REPORT_CHARS = 30_000

# Статусы, при которых есть готовый отчёт для отдачи
_READY_STATUSES = {
    ProcessingStatus.DONE.value,
    ProcessingStatus.PENDING_REVIEW.value,
    ProcessingStatus.APPROVED.value,
}

mcp = FastMCP(
    "LexRadar",
    mask_error_details=False,      # не отдавать клиенту внутренние трейсы
    on_duplicate="error",   # упасть, если имя инструмента задублировано
)


# ─── Аутентификация: API-key → user_id ────────────────────────

@dataclass(frozen=True)
class MCPPrincipal:
    """Голые данные о пользователе. Никаких ORM-объектов — сессия к моменту
    использования уже закрыта, ленивые поля отвалятся."""
    user_id: int


def resolve_mcp_principal() -> MCPPrincipal:
    """Резолвит пользователя по MCP_API_KEY тем же механизмом, что REST API."""
    api_key = os.getenv("MCP_API_KEY")
    if not api_key:
        raise RuntimeError("MCP_API_KEY не задан в окружении")

    with get_session() as session:
        user = UserRepository(session).get_by_api_key(api_key)
        if user is None:
            raise RuntimeError("Невалидный MCP_API_KEY")
        return MCPPrincipal(user_id=user.id)


# ─── Ленивая инициализация (не падаем при импорте) ────────────

@lru_cache(maxsize=1)
def get_principal() -> MCPPrincipal:
    return resolve_mcp_principal()


@lru_cache(maxsize=1)
def get_chroma_store() -> ChromaStore:
    return ChromaStore()


@lru_cache(maxsize=1)
def get_storage() -> StorageService:
    return StorageService()


# ─── Вспомогательное ──────────────────────────────────────────

def _normalize_inn(inn: str) -> str:
    """Оставляет только цифры: 'ИНН 7707 123' → '7707123'."""
    normalized = "".join(ch for ch in inn if ch.isdigit())
    if not normalized:
        raise ToolError("ИНН указан некорректно.")
    return normalized


# ─── Инструмент 1: контрагент ─────────────────────────────────

@mcp.tool
def lookup_counterparty(inn: str) -> dict:
    """
    Найти контрагента по ИНН в памяти пользователя.

    Возвращает, встречался ли контрагент раньше, сколько раз, когда впервые
    и последний раз. Используй, когда нужно понять историю работы с компанией
    перед подписанием нового договора.

    Args:
        inn: ИНН контрагента (строка).
    """
    inn = _normalize_inn(inn)
    principal = get_principal()

    with get_session() as session:
        cp = CounterpartyRepository(session).get(principal.user_id, inn)
        if cp is None:
            return {
                "found": False,
                "inn": inn,
                "message": "Контрагент с таким ИНН в памяти не найден.",
            }
        return {
            "found": True,
            "inn": cp.inn,
            "name": cp.name,
            "times_seen": cp.times_seen,
            "first_seen": cp.first_seen.isoformat() if cp.first_seen else None,
            "last_seen": cp.last_seen.isoformat() if cp.last_seen else None,
        }


# ─── Инструмент 2: история рисков контрагента ─────────────────

@mcp.tool
def get_counterparty_risk_history(inn: str, limit: int = 10) -> dict:
    """
    Получить историю ранее обнаруженных рисков по контрагенту (ИНН).

    Возвращает список рисков из прошлых договоров с этим контрагентом,
    свежие первыми: уровень серьёзности, текст риска, номер договора.
    Используй, чтобы предупредить о повторяющихся проблемах.

    Args:
        inn: ИНН контрагента.
        limit: сколько последних рисков вернуть (1–50, по умолчанию 10).
    """
    if not 1 <= limit <= 50:
        raise ToolError("limit должен быть от 1 до 50.")

    inn = _normalize_inn(inn)
    principal = get_principal()

    with get_session() as session:
        risks = CounterpartyRiskRepository(session).list_by_counterparty(
            principal.user_id, inn, limit=limit
        )
        if not risks:
            return {
                "inn": inn,
                "count": 0,
                "risks": [],
                "message": "По этому контрагенту рисков в истории нет.",
            }
        return {
            "inn": inn,
            "count": len(risks),
            "risks": [
                {
                    "severity": (
                        r.severity.value
                        if hasattr(r.severity, "value")
                        else str(r.severity)
                    ),
                    "risk_text": r.risk_text,
                    "document_number": r.document_number,
                    "found_at": r.found_at.isoformat() if r.found_at else None,
                }
                for r in risks
            ],
        }


# ─── Инструмент 3: готовый анализ договора ────────────────────

@mcp.tool
def get_contract_analysis(processing_id: int) -> dict:
    """
    Получить результат анализа конкретного договора по его processing_id.

    Возвращает готовый разбор (риски + summary), если обработка завершена.
    Если договор ещё обрабатывается — сообщает об этом; если упал или отклонён —
    отдаёт причину.

    Args:
        processing_id: числовой id обработки, полученный при загрузке договора.
    """
    principal = get_principal()

    with get_session() as session:
        processing = ProcessingRepository(session).get_for_user(processing_id, principal.user_id)

        if processing is None:
            return {"found": False, "message": f"Обработка {processing_id} не найдена."}

        # Мини-security: чужой договор не отдаём (и не раскрываем, что он есть)
        # if processing.user_id != principal.user_id:
        #     return {"found": False, "message": f"Обработка {processing_id} не найдена."}

        status = processing.status

        if status == ProcessingStatus.PROCESSING.value:
            return {"found": True, "status": status,
                    "message": "Договор ещё обрабатывается, попробуйте позже."}

        if status == ProcessingStatus.FAILED.value:
            return {"found": True, "status": status,
                    "error": processing.error_message}

        if status == ProcessingStatus.REJECTED.value:
            return {"found": True, "status": status,
                    "message": "Договор отклонён при проверке."}

        if status not in _READY_STATUSES:
            return {"found": True, "status": status,
                    "message": f"Результат в статусе '{status}' недоступен."}

        # done / pending_review / approved → читаем результат из файла
        if not processing.result_path:
            return {"found": True, "status": status,
                    "message": "Результат недоступен (нет пути к файлу)."}

        try:
            report = get_storage().read_text(processing.result_path)
        except FileNotFoundError:
            return {"found": True, "status": status,
                    "message": "Файл результата не найден на диске."}

        return {
            "found": True,
            "status": status,
            "filename": processing.original_filename,
            "report": report[:MAX_REPORT_CHARS],
            "truncated": len(report) > MAX_REPORT_CHARS,
        }


# ─── Инструмент 4: поиск по справочной базе legal_docs ────────

@mcp.tool
def search_legal_knowledge(query: str, top_k: int = 3) -> dict:
    """
    Семантический поиск по справочной юридической базе (коллекция legal_docs).

    Возвращает наиболее релевантные фрагменты из эталонной базы знаний —
    типовые формулировки, нормы, на которые опирается анализ рисков.
    Используй, чтобы свериться с образцовыми положениями.

    Args:
        query: текст запроса на естественном языке.
        top_k: сколько фрагментов вернуть (1–10, по умолчанию 3).
    """
    if not 1 <= top_k <= 10:
        raise ToolError("top_k должен быть от 1 до 10.")

    chunks = get_chroma_store().retrieve(query, top_k=top_k)
    return {
        "query": query,
        "count": len(chunks),
        "results": chunks,  # retrieve возвращает list[str]
    }


if __name__ == "__main__":
    mcp.run()  # stdio по умолчанию