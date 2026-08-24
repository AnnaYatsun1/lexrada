"""
Eval retrieval-компонента LexRadar: сравнение baseline (bi-encoder / Chroma HNSW)
против retrieve_with_rerank (+ cross-encoder) на golden_retrieval.json.

Метрики: Precision@1 (= Hit@1) и Recall@5 (= Hit@5), т.к. в этой версии
golden set у каждого кейса ровно один gold-документ (см. metric_notes
в самом golden_retrieval.json).

Запуск из корня: python3 -m scripts.evals.run_retrieval_eval

ВАЖНО перед запуском:
    Проверь METADATA_ID_FIELD ниже — это имя поля в metadata чанка,
    по которому сверяем совпадение с relevant_documents из golden set
    (например "kzot_article_21.md"). Обычно "source" или "file" —
    уточни, как называется поле у тебя в pipeline индексации.
"""
import argparse
import json
from dotenv import load_dotenv
load_dotenv()

from pathlib import Path
from statistics import mean, median
from time import perf_counter

from paths import GOLDEN_DATASET_DIR, ARTIFACTS_DIR
from execution.gateways.vectors import ChromaStore
from execution.gateways.reranker import get_reranker
from execution.rag.rag_service import init_rag_db

# Поле в metadata чанка, идентифицирующее исходный документ.
# ПРОВЕРЬ И ПОПРАВЬ под свою реальную схему metadata.
METADATA_ID_FIELD = "file"

BASELINE_TOP_K = 5
RERANK_FETCH_K = 20
RERANK_TOP_K = 5

GOLDEN_PATH = GOLDEN_DATASET_DIR / "golden_retrieval.json"
OUTPUT_PATH = ARTIFACTS_DIR / "retrieval_eval_results.json"


def load_golden(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["cases"]


def doc_id_from_metadata(item: dict) -> str | None:
    """
    Достаёт id документа из результата retrieve/retrieve_with_rerank.

    Нормализуем через Path(...).name — если в metadata лежит полный путь
    (например "legal_docs/kzot_article_21.md"), сравнение с golden set
    ("kzot_article_21.md") не должно молча проваливаться из-за префикса.
    """
    metadata = item.get("metadata") or {}
    value = metadata.get(METADATA_ID_FIELD)
    if not value:
        return None
    return Path(value).name


def hit_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> bool:
    return any(doc_id in relevant_ids for doc_id in retrieved_ids[:k])


def run_baseline(store: ChromaStore, case: dict) -> list[dict]:
    """Baseline через _retrieve_candidates (bi-encoder + distance, без реранка)."""
    return store._retrieve_candidates(
        query=case["query"],
        top_k=BASELINE_TOP_K,
        filter=case.get("filter"),
    )


def run_reranked(store: ChromaStore, case: dict) -> list[dict]:
    return store.retrieve_with_rerank(
        query=case["query"],
        top_k=RERANK_TOP_K,
        fetch_k=RERANK_FETCH_K,
        filter=case.get("filter"),
    )


def evaluate(store: ChromaStore, cases: list[dict]) -> dict:
    per_case_results = []

    baseline_hits_1 = 0
    baseline_hits_5 = 0
    rerank_hits_1 = 0
    rerank_hits_5 = 0

    baseline_latencies = []
    rerank_latencies = []

    for case in cases:
        relevant_ids = set(case["relevant_documents"])

        start = perf_counter()
        baseline_results = run_baseline(store, case)
        baseline_latency = perf_counter() - start

        start = perf_counter()
        reranked_results = run_reranked(store, case)
        rerank_latency = perf_counter() - start

        baseline_ids = [doc_id_from_metadata(r) for r in baseline_results]
        reranked_ids = [doc_id_from_metadata(r) for r in reranked_results]

        b_hit1 = hit_at_k(baseline_ids, relevant_ids, k=1)
        b_hit5 = hit_at_k(baseline_ids, relevant_ids, k=5)
        r_hit1 = hit_at_k(reranked_ids, relevant_ids, k=1)
        r_hit5 = hit_at_k(reranked_ids, relevant_ids, k=5)

        baseline_hits_1 += int(b_hit1)
        baseline_hits_5 += int(b_hit5)
        rerank_hits_1 += int(r_hit1)
        rerank_hits_5 += int(r_hit5)

        baseline_latencies.append(baseline_latency)
        rerank_latencies.append(rerank_latency)

        per_case_results.append({
            "id": case["id"],
            "domain": case["domain"],
            "difficulty": case["difficulty"],
            "query": case["query"],
            "relevant_documents": list(relevant_ids),
            "baseline": {
                "retrieved_ids": baseline_ids,
                "hit@1": b_hit1,
                "hit@5": b_hit5,
                "latency_ms": round(baseline_latency * 1000, 2),
            },
            "reranked": {
                "retrieved_ids": reranked_ids,
                "hit@1": r_hit1,
                "hit@5": r_hit5,
                "latency_ms": round(rerank_latency * 1000, 2),
            },
            # флаг кейсов, где реранк реально что-то изменил —
            # удобно для ручного разбора
            "changed": b_hit1 != r_hit1,
        })

    n = len(cases)
    summary = {
        "n_cases": n,
        "baseline": {
            "precision@1": round(baseline_hits_1 / n, 3),
            "recall@5": round(baseline_hits_5 / n, 3),
            "latency_ms_avg": round(mean(baseline_latencies) * 1000, 2),
            "latency_ms_median": round(median(baseline_latencies) * 1000, 2),
        },
        "reranked": {
            "precision@1": round(rerank_hits_1 / n, 3),
            "recall@5": round(rerank_hits_5 / n, 3),
            "latency_ms_avg": round(mean(rerank_latencies) * 1000, 2),
            "latency_ms_median": round(median(rerank_latencies) * 1000, 2),
        },
    }

    return {"summary": summary, "cases": per_case_results}


def print_report(report: dict) -> None:
    s = report["summary"]
    print("=" * 60)
    print(f"Cases evaluated: {s['n_cases']}")
    print("-" * 60)
    print(f"{'Metric':<20}{'Baseline':<12}{'Reranked':<12}{'Delta':<10}")
    for metric in ("precision@1", "recall@5"):
        b = s["baseline"][metric]
        r = s["reranked"][metric]
        delta = round(r - b, 3)
        sign = "+" if delta >= 0 else ""
        print(f"{metric:<20}{b:<12}{r:<12}{sign}{delta}")

    print("-" * 60)
    for metric, label in (("latency_ms_avg", "Latency avg (ms)"), ("latency_ms_median", "Latency median (ms)")):
        b = s["baseline"][metric]
        r = s["reranked"][metric]
        delta = round(r - b, 2)
        sign = "+" if delta >= 0 else ""
        print(f"{label:<20}{b:<12}{r:<12}{sign}{delta}")
    print("=" * 60)

    changed = [c for c in report["cases"] if c["changed"]]
    if changed:
        print(f"\nКейсы, где реранк изменил hit@1 ({len(changed)}):")
        for c in changed:
            arrow = "improved" if c["reranked"]["hit@1"] else "regressed"
            print(f"  [{arrow}] {c['id']} ({c['domain']}/{c['difficulty']}): {c['query'][:70]}...")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", default=str(GOLDEN_PATH), help="Путь к golden_retrieval.json")
    parser.add_argument("--out", default=str(OUTPUT_PATH), help="Куда сохранить детальный результат")
    args = parser.parse_args()

    print("🎯 Retrieval eval для LexRadar\n")

    init_rag_db()
    store = ChromaStore()

    cases = load_golden(args.golden)
    print(f"📄 Загружено {len(cases)} кейсов из {args.golden}\n")

    # Прогрев: первый вызов CrossEncoder грузит веса модели (секунды),
    # без прогрева эта задержка осядет в latency первого кейса и исказит
    # среднее/медиану. Прогоняем реранкер на пустышке до основного цикла.
    print("⚖️  Прогреваю reranker...\n")
    get_reranker().rerank(query="warmup", documents=[{"content": "warmup document"}], top_k=1)

    report = evaluate(store, cases)
    print_report(report)

    ARTIFACTS_DIR.mkdir(exist_ok=True)
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n💾 Детальный результат сохранён в {args.out}")


if __name__ == "__main__":
    main()