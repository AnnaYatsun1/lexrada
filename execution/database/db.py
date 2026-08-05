import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime
from paths import DB_PATH


PRICING = {
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.00},
}


def init_db():
    conn = sqlite3.connect(DB_PATH)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS processings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_hash TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            completed_at TEXT,
            result_path TEXT,
            error_message TEXT,
            delivery_channel TEXT,          -- 'telegram', 'email', 'slack', ...
            delivery_status TEXT,            -- 'pending', 'sent', 'failed', 'skipped'
            delivery_attempt_count INTEGER DEFAULT 0,
            delivery_error TEXT,
            delivered_at TEXT
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            processing_id INTEGER NOT NULL,
            model TEXT NOT NULL,
            stage TEXT NOT NULL,
            tokens_in INTEGER NOT NULL,
            tokens_out INTEGER NOT NULL,
            latency_ms INTEGER NOT NULL,
            cost_usd REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'success',
            created_at TEXT NOT NULL,
            FOREIGN KEY (processing_id) REFERENCES processings(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS counterparties (
            inn TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            times_seen INTEGER DEFAULT 1,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS counterparty_risks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            counterparty_inn TEXT NOT NULL,
            processing_id INTEGER NOT NULL,
            document_number TEXT,
            risk_text TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'MEDIUM',
            found_at TEXT NOT NULL,
            FOREIGN KEY (counterparty_inn) REFERENCES counterparties(inn),
            FOREIGN KEY (processing_id) REFERENCES processings(id)
        )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        api_key TEXT UNIQUE NOT NULL,
        name TEXT,
        telegram_chat_id TEXT,
        telegram_username TEXT,
        preferred_delivery TEXT DEFAULT 'telegram',
        created_at TEXT NOT NULL
    )
""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_calls_processing ON llm_calls(processing_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_calls_created ON llm_calls(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cp_risks_inn ON counterparty_risks(counterparty_inn)")

    conn.commit()
    conn.close()


def compute_file_hash(file_path: Path) -> str:
    """Считает SHA-256 от содержимого файла."""
    h = hashlib.sha256()
    h.update(file_path.read_bytes())
    return h.hexdigest()

def get_user_by_id(user_id: int) -> dict | None:
    """Возвращает юзера по id."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        """SELECT id, email, name, api_key, telegram_chat_id, 
                  telegram_username, preferred_delivery 
           FROM users WHERE id = ?""",
        (user_id,)
    ).fetchone()
    conn.close()
    
    if not row:
        return None
    
    return {
        "id": row[0],
        "email": row[1],
        "name": row[2],
        "api_key": row[3],
        "telegram_chat_id": row[4],
        "telegram_username": row[5],
        "preferred_delivery": row[6],
    }


def get_user_by_api_key(api_key: str) -> dict | None:
    """Возвращает юзера по api_key (для X-API-Key auth)."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT id FROM users WHERE api_key = ?",
        (api_key,)
    ).fetchone()
    conn.close()
    
    if not row:
        return None
    
    return get_user_by_id(row[0])

def is_already_processed(file_hash: str, user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "SELECT id FROM processings WHERE file_hash = ? AND status = 'done' AND user_id = ?",
        (file_hash, user_id)
    )
    result = cursor.fetchone()
    conn.close()
    return result is not None


def record_start(file_hash: str, filename: str, user_id: int) -> int:
    """Создаёт запись о начале обработки. Возвращает id."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "INSERT INTO processings (file_hash, original_filename, status, created_at, user_id) VALUES (?, ?, 'processing', ?, ?)",
        (file_hash, filename, datetime.utcnow().isoformat(), user_id)
    )
    processing_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return processing_id


def record_success(processing_id: int, result_path: str):
    """Помечает обработку как успешную."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE processings SET status='done', completed_at=?, result_path=? WHERE id=?",
        (datetime.utcnow().isoformat(), result_path, processing_id)
    )
    conn.commit()
    conn.close()

def record_delivery_attempt(
    processing_id: int,
    channel: str,
    success: bool,
    latency_ms: int,
    error_message: str = None
):
    """Логирует попытку доставки в processings таблице"""
    conn = sqlite3.connect(DB_PATH)
    
    status = 'sent' if success else 'failed'
    error = error_message if not success else None
    delivered_at = datetime.utcnow().isoformat() if success else None
    
    cursor = conn.execute(
        """UPDATE processings 
           SET delivery_channel = ?, 
               delivery_status = ?, 
               delivery_attempt_count = delivery_attempt_count + 1,
               delivery_error = ?,
               delivered_at = ?
           WHERE id = ?""",
        (channel, status, error, delivered_at, processing_id)
    )
    
    conn.commit()
    conn.close()
    
def record_failure(processing_id: int, error_message: str):
    """Помечает обработку как упавшую."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE processings SET status='failed', completed_at=?, error_message=? WHERE id=?",
        (datetime.utcnow().isoformat(), error_message, processing_id)
    )
    conn.commit()
    conn.close()


def calculate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Считает стоимость в USD (до 4 знаков)."""
    if model not in PRICING:
        return 0.0
    
    prices = PRICING[model]
    cost = (tokens_in * prices["input"] + tokens_out * prices["output"]) / 1_000_000
    return round(cost, 4)


def record_llm_metric(
    processing_id: int,
    user_id: int,
    model: str,
    stage: str,
    tokens_in: int,
    tokens_out: int,
    latency_ms: int,
    cost_usd: float,
    status: str = "success"
):
    """Логирует метрики одного LLM-вызова."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO llm_calls (processing_id, user_id, model, stage, tokens_in, tokens_out, latency_ms, cost_usd, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            processing_id,
            user_id,
            model,
            stage,
            tokens_in,
            tokens_out,
            latency_ms,
            cost_usd,
            status,
            datetime.utcnow().isoformat()
        )
    )
    conn.commit()
    conn.close()

def save_counterparty(inn: str, name: str, user_id: int):
    conn = sqlite3.connect(DB_PATH)
    now = datetime.utcnow().isoformat()

    existing = conn.execute(
        "SELECT times_seen FROM counterparties WHERE inn = ? AND user_id = ?",
        (inn, user_id)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE counterparties SET times_seen = times_seen + 1, last_seen = ? WHERE inn = ? AND user_id = ?",
            (now, inn, user_id)
        )
    else:
        conn.execute(
            "INSERT INTO counterparties (inn, name, times_seen, first_seen, last_seen, user_id) VALUES (?, ?, 1, ?, ?, ?)",
            (inn, name, now, now, user_id)
        )

    conn.commit()
    conn.close()


def save_counterparty_risk(counterparty_inn: str, processing_id: int, user_id: int,
                           document_number: str, risk_text: str, severity: str = "MEDIUM"):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT INTO counterparty_risks
           (counterparty_inn, processing_id, user_id, document_number, risk_text, severity, found_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (counterparty_inn, processing_id, user_id, document_number, risk_text, severity,
         datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()

def get_counterparty_history(inn: str, user_id: int) -> dict:
    conn = sqlite3.connect(DB_PATH)

    cp = conn.execute(
        "SELECT name, times_seen, first_seen, last_seen FROM counterparties WHERE inn = ? AND user_id = ?",
        (inn, user_id)
    ).fetchone()

    if not cp:
        conn.close()
        return None

    risks = conn.execute(
        """SELECT document_number, risk_text, severity, found_at
           FROM counterparty_risks
           WHERE counterparty_inn = ? AND user_id = ?
           ORDER BY found_at DESC
           LIMIT 10""",
        (inn, user_id)
    ).fetchall()

    conn.close()

    return {
        "name": cp[0],
        "times_seen": cp[1],
        "first_seen": cp[2],
        "last_seen": cp[3],
        "risks": [
            {
                "document_number": r[0],
                "risk_text": r[1],
                "severity": r[2],
                "found_at": r[3],
            }
            for r in risks
        ],
    }