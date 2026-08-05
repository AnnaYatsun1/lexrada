import os
os.environ.setdefault("ANTHROPIC_API_KEY", open(".env").read().split("=",1)[1].strip())

from pathlib import Path
from execution.gateways.llm import AnthropicLLM
from execution.services.extraction import ExtractionService
from paths import DIRECTIVES_DIR, INPUT_DIR
import anthropic

client = anthropic.Anthropic(timeout=60)
llm = AnthropicLLM(client)
es = ExtractionService(
    llm=llm,
    directive=Path(DIRECTIVES_DIR / "contract_analysis_v2.md").read_text(encoding="utf-8")
)

for name in ["contract_7.txt", "contract_9.txt"]:
    path = INPUT_DIR / name
    if not path.exists():
        print(f"skip {name}")
        continue
    text = path.read_text(encoding="utf-8")
    result = es.extract(text, processing_id=0)
    print(f"\n=== {name} ===")
    d = result.model_dump()
    for k, v in d.items():
        if k != "parties":
            print(f"  {k}: {v}")
