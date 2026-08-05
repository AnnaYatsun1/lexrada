#!/usr/bin/env python3
import json, sys
from pathlib import Path
from pydantic import ValidationError
from execution.eval.runner import EvalRunner
from execution.gateways.llm import AnthropicLLM
from execution.services.extraction import ExtractionService
from execution.lodder.logger import setup_logging, get_logger
from execution.models.contract import AgreementContractOutput
from evaluation.golden_dataset.models import load_golden
from paths import DIRECTIVES_DIR, INPUT_DIR
import anthropic
import os
from dotenv import load_dotenv

load_dotenv()

print("KEY:", os.getenv("ANTHROPIC_API_KEY"))
setup_logging()
logger = get_logger(__name__)

GOLDEN_PATH = Path("golden_dataset/golden_contracts.json")
if not GOLDEN_PATH.exists():
    print(f"❌ {GOLDEN_PATH} не найден")
    sys.exit(1)

with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
    golden_data = json.load(f)

golden_contracts = load_golden(str(GOLDEN_PATH))
# golden_contracts = {}
# for item in golden_data:
#     for contract_id, contract_data in item.items():
#         golden_contracts[contract_id] = contract_data

print(f"✅ Загружено {len(golden_contracts)} контрактов")

client = anthropic.Anthropic(timeout=60)
llm = AnthropicLLM(client)
extraction_service = ExtractionService(
    llm=llm,
    directive=Path(DIRECTIVES_DIR / "contract_analysis_v2.md").read_text(encoding="utf-8"),
)

runner = EvalRunner(
    extraction_service=extraction_service,
    input_dir=INPUT_DIR,
    llm=llm,
)
results = runner.run(golden_contracts)
runner.print_report(results)
runner.save_results(results)

def eval_contract(contract_id: str, contract_data: dict) -> dict:
    print(f"\n📋 {contract_id}...")
    file_path = INPUT_DIR / contract_data["file"]
    if not file_path.exists():
        return {"contract_id": contract_id, "status": "SKIP", "reason": "файл не найден"}
    
    try:
        contract_text = file_path.read_text(encoding="utf-8")
        actual_output = extraction_service.extract(contract_text, processing_id=0)
        print("\nACTUAL:")
        print(actual_output.model_dump())   
         
    except Exception as e:
        return {"contract_id": contract_id, "status": "ERROR", "reason": str(e)[:100]}
    
    expected_output = contract_data["expected_output"]
    print(expected_output["document_number"])
    print(actual_output.document_number)
    correct = sum(1 for f, e in expected_output.items() if getattr(actual_output, f, None) == e)
    total = len(expected_output)
    accuracy = (correct / total * 100) if total > 0 else 0
    
    return {
        "contract_id": contract_id,
        "status": "OK",
        "accuracy": round(accuracy, 2),
        "correct": correct,
        "total": total
    }

print("\n🧪 EVALS START")