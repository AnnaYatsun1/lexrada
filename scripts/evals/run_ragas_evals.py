"""
RAGAS eval для RAG-компонента LexRadar.
Запуск из корня: python3 -m scripts.evals.run_ragas_evals
"""
import os
from dotenv import load_dotenv
load_dotenv()

import anthropic
from datasets import Dataset

from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_anthropic import ChatAnthropic
from langchain_community.embeddings import HuggingFaceEmbeddings

from paths import INPUT_DIR, GOLDEN_DATASET_DIR, ARTIFACTS_DIR
from execution.gateways.llm import AnthropicLLM
from execution.gateways.vectors import ChromaStore
from execution.rag.rag_service import init_rag_db
from evaluation.models import load_golden


init_rag_db()
vectors = ChromaStore()
llm = AnthropicLLM(anthropic.Anthropic(timeout=60))

GOLDEN_PATH = GOLDEN_DATASET_DIR / "golden_contracts.json"


def ask_with_context(question: str, contexts: list[str]) -> str:
    """Упрощённый анализ рисков с RAG-контекстом. Использует production AnthropicLLM."""
    context_block = "\n\n---\n\n".join(contexts)
    prompt = f"""Ты юрист-аналитик. Проанализируй договор и найди юридические, 
финансовые и операционные риски. Используй только информацию из контекста 
типовых договоров для сравнения. Не выдумывай факты.

<похожие_типовые_договоры>
{context_block}
</похожие_типовые_договоры>

<анализируемый_договор>
{question}
</анализируемый_договор>

Кратко (5-10 предложений) опиши основные риски."""

    # processing_id НЕ передаём → метрика не пишется в БД
    resp = llm.create(
        model="claude-haiku-4-5",
        messages=[{"role": "user", "content": prompt}],
        stage="ragas_eval",
        max_tokens=1500,
    )
    return resp.content[0].text


def build_eval_dataset(n_contracts: int = 2) -> Dataset:
    golden = load_golden(str(GOLDEN_PATH))[:n_contracts]
    samples = {"question": [], "contexts": [], "answer": []}

    for gc in golden:
        contract_path = INPUT_DIR / gc.file
        if not contract_path.exists():
            print(f"⚠️  Файл {gc.file} не найден, пропускаем")
            continue

        contract_text = contract_path.read_text(encoding="utf-8")
        print(f"📄 Обрабатываю: {gc.file}")

        query = gc.expected_output.subject or contract_text[:500]
        print(f"   → Query: {query[:100]}")
              
        contexts = vectors.retrieve(query=query, top_k=3)
        print(f"   → Retrieved {len(contexts)} документов")

        answer = ask_with_context(contract_text, contexts)
        print(f"   → Answer сгенерирован ({len(answer)} символов)")

        samples["question"].append(contract_text)
        samples["contexts"].append(contexts)
        samples["answer"].append(answer)

    return Dataset.from_dict(samples)


def main():
    print("🎯 RAGAS eval для LexRadar\n")
    print("📊 Собираю данные...\n")
    dataset = build_eval_dataset(n_contracts=2)
    print(f"\n✅ Собрано {len(dataset)} примеров\n")

    judge_llm = LangchainLLMWrapper(ChatAnthropic(
        model="claude-haiku-4-5",
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        max_tokens=3500,
    ))
    embeddings = LangchainEmbeddingsWrapper(HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    ))

    print("⚖️  Запуск RAGAS (Claude как судья)...\n")
    result = evaluate(
        dataset=dataset,
        metrics=[faithfulness, answer_relevancy],
                #  , context_precision],
        llm=judge_llm,
        embeddings=embeddings,
    )

    print("\n🎉 Результаты:\n")
    print(result)

    ARTIFACTS_DIR.mkdir(exist_ok=True)
    output_path = ARTIFACTS_DIR / "ragas_baseline.json"
    result.to_pandas().to_json(output_path, orient="records", indent=2, force_ascii=False)
    print(f"\n💾 Сохранено в {output_path}")


if __name__ == "__main__":
    main()