import re
from abc import ABC, abstractmethod
from typing import Any

# Match ids become file/blob names, so they are restricted to a safe character set.
_MATCH_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def is_valid_match_id(match_id: str) -> bool:
    return bool(_MATCH_ID_RE.match(match_id or ""))


def require_valid_match_id(match_id: str) -> None:
    if not is_valid_match_id(match_id):
        raise ValueError(f"Invalid match id: {match_id!r}")


class StorageProvider(ABC):
    """Persists match documents as JSON. Implementations must be interchangeable."""

    @abstractmethod
    def save_match(self, match: dict[str, Any]) -> None: ...

    @abstractmethod
    def load_match(self, match_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def list_matches(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def delete_match(self, match_id: str) -> bool: ...
