# from sentence_transformers import CrossEncoder
from functools import lru_cache

from functools import lru_cache


class Reranker:
    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
    ):
        # Тяжёлый импорт происходит только когда реально создаём reranker
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(model_name)

    def rerank(
        self,
        query: str,
        documents: list[dict],
        top_k: int = 3,
    ) -> list[dict]:
        if not documents:
            return []

        pairs = [
            [query, document["content"]]
            for document in documents
        ]

        scores = self._model.predict(pairs)

        ranked = sorted(
            zip(documents, scores),
            key=lambda item: item[1],
            reverse=True,
        )

        return [
            {
                **document,
                "rerank_score": float(score),
            }
            for document, score in ranked[:top_k]
        ]


@lru_cache(maxsize=1)
def get_reranker() -> Reranker:
    return Reranker()