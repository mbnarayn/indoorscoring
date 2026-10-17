import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    storage_provider: str = field(default_factory=lambda: os.getenv("STORAGE_PROVIDER", "local").strip().lower())
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "data")))
    azure_connection_string: str | None = field(default_factory=lambda: os.getenv("AZURE_STORAGE_CONNECTION_STRING") or None)
    azure_account_url: str | None = field(default_factory=lambda: os.getenv("AZURE_STORAGE_ACCOUNT_URL") or None)
    azure_container: str = field(default_factory=lambda: os.getenv("AZURE_STORAGE_CONTAINER", "matches"))
    max_import_bytes: int = field(default_factory=lambda: int(os.getenv("MAX_IMPORT_BYTES", str(2 * 1024 * 1024))))
    delete_password: str = field(default_factory=lambda: os.getenv("DELETE_PASSWORD") or "miltonkeynes600028")
    scorer_password: str = field(default_factory=lambda: os.getenv("SCORER_PASSWORD") or "scorer28")


def get_settings() -> Settings:
    return Settings()
