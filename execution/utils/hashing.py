"""Утилиты хеширования — идентификация файлов и содержимого."""
import hashlib
from pathlib import Path


def compute_file_hash(file_path: Path) -> str:
    """SHA-256 файла с диска (для CLI-режима когда файл уже на файловой системе)."""
    h = hashlib.sha256()
    h.update(file_path.read_bytes())
    return h.hexdigest()


def compute_content_hash(content: bytes) -> str:
    """SHA-256 байтов (для HTTP-загрузки, файл ещё в памяти)."""
    return hashlib.sha256(content).hexdigest()