import json
import logging
from typing import Any

from app.storage.base import StorageProvider, is_valid_match_id, require_valid_match_id

logger = logging.getLogger(__name__)


class AzureBlobStorageProvider(StorageProvider):
    """Stores each match as a JSON blob named <match_id>.json in a container.

    Authentication: prefers Managed Identity / DefaultAzureCredential via AZURE_STORAGE_ACCOUNT_URL;
    falls back to AZURE_STORAGE_CONNECTION_STRING when supplied.
    """

    def __init__(self, container: str, account_url: str | None = None, connection_string: str | None = None):
        # Imported lazily so the Azure SDK is only needed when this provider is selected.
        from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
        from azure.storage.blob import BlobServiceClient, ContentSettings

        self._not_found = ResourceNotFoundError
        self._content_settings = ContentSettings(content_type="application/json")

        retry_kwargs = {"retry_total": 5, "retry_backoff_factor": 0.8, "connection_timeout": 10, "read_timeout": 30}
        if account_url:
            from azure.identity import DefaultAzureCredential

            service = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential(), **retry_kwargs)
        elif connection_string:
            service = BlobServiceClient.from_connection_string(connection_string, **retry_kwargs)
        else:
            raise ValueError("Set AZURE_STORAGE_ACCOUNT_URL (managed identity) or AZURE_STORAGE_CONNECTION_STRING.")

        self._container = service.get_container_client(container)
        try:
            self._container.create_container()
        except ResourceExistsError:
            pass

    @staticmethod
    def _blob_name(match_id: str) -> str:
        require_valid_match_id(match_id)
        return f"{match_id}.json"

    def save_match(self, match: dict[str, Any]) -> None:
        data = json.dumps(match, indent=2, ensure_ascii=False).encode("utf-8")
        self._container.upload_blob(
            self._blob_name(match["id"]), data, overwrite=True, content_settings=self._content_settings
        )

    def load_match(self, match_id: str) -> dict[str, Any] | None:
        try:
            data = self._container.download_blob(self._blob_name(match_id)).readall()
        except self._not_found:
            return None
        return json.loads(data)

    def list_matches(self) -> list[dict[str, Any]]:
        matches = []
        for blob in self._container.list_blobs():
            name: str = blob.name
            if not name.endswith(".json") or not is_valid_match_id(name[:-5]):
                continue
            try:
                match = self.load_match(name[:-5])
            except (ValueError, json.JSONDecodeError):
                logger.exception("Skipping unreadable blob %s", name)
                continue
            if match is not None:
                matches.append(match)
        return matches

    def delete_match(self, match_id: str) -> bool:
        try:
            self._container.delete_blob(self._blob_name(match_id))
        except self._not_found:
            return False
        return True
