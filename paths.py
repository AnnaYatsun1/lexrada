from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# Данные (входные/выходные)
INPUT_DIR = DATA_DIR / "input_contracts"
OUTPUT_DIR = DATA_DIR / "output"
RAG_DOCS_DIR = DATA_DIR / "rag_documents"
GOLDEN_DATASET_DIR = DATA_DIR / "golden_dataset"

# Базы данных
DB_PATH = DATA_DIR / "processings.db"
CHROMA_DB_PATH = DATA_DIR / "chroma_db"

# Артефакты и логи
ARTIFACTS_DIR = BASE_DIR / "artifacts"
LOG_DIR = BASE_DIR / "logs"

# Директивы (остаются в корне — это часть кода/промптов)
DIRECTIVES_DIR = BASE_DIR / "directives"
DATA_DIR = BASE_DIR / "data"