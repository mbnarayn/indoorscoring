import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from app.storage.base import StorageProvider, is_valid_match_id, require_valid_match_id

logger = logging.getLogger(__name__)


class LocalJsonStorageProvider(StorageProvider):
    """Stores each match as <data_dir>/matches/<match_id>.json."""

    def __init__(self, data_dir: Path):
        self._dir = Path(data_dir) / "matches"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, match_id: str) -> Path:
        require_valid_match_id(match_id)
        return self._dir / f"{match_id}.json"

    def save_match(self, match: dict[str, Any]) -> None:
        path = self._path(match["id"])
        payload = json.dumps(match, indent=2, ensure_ascii=False)
        with self._lock:
            # Write to a temp file then atomically replace so a crash never leaves a half-written match.
            fd, tmp = tempfile.mkstemp(dir=self._dir, prefix=".tmp-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(payload)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, path)
            except BaseException:
                if os.path.exists(tmp):
                    os.remove(tmp)
                raise

    def load_match(self, match_id: str) -> dict[str, Any] | None:
        path = self._path(match_id)
        with self._lock:
            if not path.exists():
                return None
            return json.loads(path.read_text(encoding="utf-8"))

    def list_matches(self) -> list[dict[str, Any]]:
        matches = []
        with self._lock:
            for path in sorted(self._dir.glob("*.json")):
                if not is_valid_match_id(path.stem):
                    continue
                try:
                    matches.append(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    logger.exception("Skipping unreadable match file %s", path.name)
        return matches

    def delete_match(self, match_id: str) -> bool:
        path = self._path(match_id)
        with self._lock:
            if not path.exists():
                return False
            path.unlink()
            return True
