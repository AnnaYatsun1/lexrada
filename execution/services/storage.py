"""Работа с файлами: uploads, results, temporary files."""
from pathlib import Path

from paths import DATA_DIR


class StorageService:
    def __init__(
        self,
        base_dir: Path | None = None,
    ):
        self._base_dir = base_dir or (DATA_DIR / "uploads")
        self._base_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    def save_upload(
        self,
        content: bytes,
        processing_id: int,
        filename: str,
    ) -> Path:
        safe_filename = Path(filename).name

        file_path = (
            self._base_dir
            / f"{processing_id}_{safe_filename}"
        )

        file_path.write_bytes(content)
        return file_path

    def read_text(
        self,
        file_path: str | Path,
    ) -> str:
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(
                f"File not found: {path}"
            )

        return path.read_text(encoding="utf-8")

    def delete(
        self,
        file_path: str | Path,
    ) -> None:
        Path(file_path).unlink(missing_ok=True)

    def exists(
        self,
        file_path: str | Path,
    ) -> bool:
        return Path(file_path).exists()