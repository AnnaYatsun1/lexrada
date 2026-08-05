"""
EvalRunner — запускает eval на golden dataset.
Использует конфиги exact_fields / normalized_fields / semantic_fields.
"""
import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from .comparators import compare_exact, compare_normalized, compare_semantic


@dataclass
class ContractEvalResult:
    contract_id: str
    status: str  # OK / ERROR / SKIP
    reason: Optional[str] = None

    exact: float = 0.0
    normalized: float = 0.0
    semantic: float = 0.0
    overall: float = 0.0

    field_details: dict = field(default_factory=dict)


class EvalRunner:
    def __init__(self, extraction_service, input_dir: Path, llm = None):
        self.extraction_service = extraction_service
        self.input_dir = input_dir
        self.llm = llm

    def eval_one(self, golden_contract) -> ContractEvalResult:
        """Прогоняет один контракт"""
        cid = golden_contract.contract_id
        file_path = self.input_dir / golden_contract.file

        if not file_path.exists():
            return ContractEvalResult(
                contract_id=cid, status="SKIP",
                reason=f"файл {golden_contract.file} не найден"
            )

        # Читаем текст
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception as e:
            return ContractEvalResult(
                contract_id=cid, status="ERROR", reason=f"чтение: {e}"
            )

        # Extraction
        try:
            actual = self.extraction_service.extract(text, processing_id=0)
        except Exception as e:
            return ContractEvalResult(
                contract_id=cid, status="ERROR",
                reason=f"extraction: {str(e)[:100]}"
            )

        expected = golden_contract.expected_output

        # Конфигурация уровней сравнения
        exact_fields = set(golden_contract.exact_fields) if golden_contract.exact_fields else set()
        normalized_fields = set(golden_contract.normalized_fields) if golden_contract.normalized_fields else set()
        semantic_fields = set(golden_contract.semantic_fields) if golden_contract.semantic_fields else set()

        # Если ничего не конфигурировано — используем все поля как normalized (default)
        if not (exact_fields or normalized_fields or semantic_fields):
            # DEFAULT: все поля сравниваем как normalized
            normalized_fields = set(expected.model_dump().keys()) - {"parties"}

        # Сравнение
        act_dict = actual.model_dump()
        exp_dict = expected.model_dump()

        total = 0
        exact_ok = 0
        norm_ok = 0
        sem_ok = 0

        field_details = {}

        for field_name, exp_val in exp_dict.items():
            if field_name == "parties":
                continue  # parties отдельно
            if exp_val is None:
                continue

            act_val = act_dict.get(field_name)
            total += 1

            # Выбираем уровень сравнения
            if field_name in exact_fields:
                is_match = compare_exact(act_val, exp_val)
                if is_match:
                    exact_ok += 1
                    norm_ok += 1
                    sem_ok += 1
            elif field_name in semantic_fields:
                is_match = compare_semantic(act_val, exp_val, field_name, self.llm)
                if is_match:
                    sem_ok += 1
                # Проверяем также normalized и exact для статистики
                if compare_normalized(act_val, exp_val, field_name):
                    norm_ok += 1
                if compare_exact(act_val, exp_val):
                    exact_ok += 1
            else:  # normalized (default)
                is_match = compare_normalized(act_val, exp_val, field_name)
                if is_match:
                    norm_ok += 1
                # Проверяем также exact и semantic
                if compare_exact(act_val, exp_val):
                    exact_ok += 1
                if compare_semantic(act_val, exp_val, field_name, self.llm):
                    sem_ok += 1

            field_details[field_name] = {
                "expected": str(exp_val)[:60],
                "actual": str(act_val)[:60],
                "level": "exact" if field_name in exact_fields else ("semantic" if field_name in semantic_fields else "normalized"),
            }

        if total == 0:
            return ContractEvalResult(
                contract_id=cid, status="OK",
                exact=100.0, normalized=100.0, semantic=100.0, overall=100.0
            )

        exact_pct = round(exact_ok / total * 100, 2)
        norm_pct = round(norm_ok / total * 100, 2)
        sem_pct = round(sem_ok / total * 100, 2)
        overall = round((exact_pct + norm_pct + sem_pct) / 3, 2)

        return ContractEvalResult(
            contract_id=cid,
            status="OK",
            exact=exact_pct,
            normalized=norm_pct,
            semantic=sem_pct,
            overall=overall,
            field_details=field_details,
        )

    def run(self, golden_contracts: list) -> list[ContractEvalResult]:
        """Прогоняет все контракты"""
        return [self.eval_one(gc) for gc in golden_contracts]

    @staticmethod
    def print_report(results: list[ContractEvalResult]):
        """Печатает EVAL REPORT"""
        print("\n" + "=" * 70)
        print("📊 EVAL REPORT")
        print("=" * 70)

        ok_results = [r for r in results if r.status == "OK"]
        error_results = [r for r in results if r.status == "ERROR"]
        skip_results = [r for r in results if r.status == "SKIP"]

        print(f"\nВсего: {len(results)} | ✅ OK: {len(ok_results)} | ❌ ERR: {len(error_results)} | ⏭ SKIP: {len(skip_results)}")

        # Детали по контрактам
        print("\n" + "-" * 70)
        print(f"{'Contract':<20} {'Exact':>10} {'Normal':>10} {'Semantic':>10} {'Overall':>10}")
        print("-" * 70)

        for r in results:
            if r.status == "OK":
                emoji = "✅" if r.overall >= 80 else "⚠️" if r.overall >= 50 else "❌"
                print(f"{emoji} {r.contract_id:<18} {r.exact:>9.1f}% {r.normalized:>9.1f}% {r.semantic:>9.1f}% {r.overall:>9.1f}%")

                # Проблемные поля
                bad = [f for f, d in r.field_details.items()]
                if bad:
                    print(f"   fields: {', '.join(bad[:5])}")
            elif r.status == "ERROR":
                print(f"❌ {r.contract_id:<18} {r.reason[:50]}")
            else:
                print(f"⏭  {r.contract_id:<18} {r.reason[:50]}")

        # Итого
        if ok_results:
            avg_exact = sum(r.exact for r in ok_results) / len(ok_results)
            avg_norm = sum(r.normalized for r in ok_results) / len(ok_results)
            avg_sem = sum(r.semantic for r in ok_results) / len(ok_results)
            avg_overall = sum(r.overall for r in ok_results) / len(ok_results)

            print("\n" + "=" * 70)
            print(f"  Exact fields:      {avg_exact:.1f}%")
            print(f"  Normalized fields: {avg_norm:.1f}%")
            print(f"  Semantic fields:   {avg_sem:.1f}%")
            print(f"  ─────────────────────────")
            print(f"  Overall:           {avg_overall:.1f}%")
            print("=" * 70)

    @staticmethod
    def save_results(results: list[ContractEvalResult], path: str = "eval_results.json"):
        """Сохраняет результаты в JSON"""
        data = []
        for r in results:
            data.append({
                "contract_id": r.contract_id,
                "status": r.status,
                "reason": r.reason,
                "exact": r.exact,
                "normalized": r.normalized,
                "semantic": r.semantic,
                "overall": r.overall,
            })
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n💾 Сохранено: {path}")