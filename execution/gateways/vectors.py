import chromadb
from typing import Protocol
# from execution.gateways.reranker import get_reranker
from execution.rag.rag_service import build_where
from execution.rag.rag_service import init_rag_db
from paths import CHROMA_DB_PATH


class VectorStore(Protocol):
    def retrieve(self, query: str, top_k: int = 3) -> list[str]: ...


class ChromaStore:
        """Обёртка над ChromaDB для семантического поиска договоров."""

        def __init__(self):
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

        
        def retrieve_with_rerank(
            self,
            query: str,
            top_k: int = 3,
            fetch_k: int = 20,
            filter: dict | None = None,
        ) -> list[dict]:
            from execution.gateways.reranker import get_reranker
            if fetch_k < top_k:
                raise ValueError("fetch_k должен быть >= top_k")

            candidates = self._retrieve_candidates(
                query=query,
                top_k=fetch_k,
                filter=filter,
            )

            return get_reranker().rerank(
                query=query,
                documents=candidates,
                top_k=top_k,
            )
        
        def _retrieve_candidates(
            self,
            query: str,
            top_k: int = 3,
            filter: dict | None = None,
        ) -> list[dict]:
            """
            Возвращает полные данные кандидатов для дальнейшего reranking/evaluation.
            """

            query_kwargs = {
                "query_texts": [query],
                "n_results": top_k,
                "include": ["documents", "metadatas", "distances"],
            }

            if filter:
                query_kwargs["where"] = build_where(filter)

            results = self._collection.query(**query_kwargs)

            ids = results["ids"][0] if results["ids"] else []
            documents = results["documents"][0] if results["documents"] else []
            metadatas = results["metadatas"][0] if results["metadatas"] else []
            distances = results["distances"][0] if results["distances"] else []

            return [
                {
                    "id": doc_id,
                    "content": document,
                    "metadata": metadata or {},
                    "distance": float(distance) if distance is not None else None,
                }
                for doc_id, document, metadata, distance
                in zip(ids, documents, metadatas, distances)
            ]


        from functools import lru_cache

  