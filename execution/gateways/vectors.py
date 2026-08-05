import chromadb
from typing import Protocol
from execution.rag.rag_service import build_where
from paths import CHROMA_DB_PATH  # ← используем централизованный путь


class VectorStore(Protocol):
    def retrieve(self, query: str, top_k: int = 3) -> list[str]: ...


class ChromaStore:
    """Обёртка над ChromaDB для семантического поиска договоров."""

    def __init__(self):
        from execution.rag.rag_service import init_rag_db
        self._client, self._collection = init_rag_db()

    def retrieve(self, query: str, top_k: int = 3, filter: dict | None = None) -> list[str]:
        query_kwargs = {
            "query_texts": [query], 
            "n_results": top_k}
        if filter:
            query_kwargs["where"] = build_where(filter)
        results = self._collection.query(**query_kwargs)
        retrieved_docs = results["documents"][0] if results["documents"] else []
        return retrieved_docs