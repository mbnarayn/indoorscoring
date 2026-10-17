from app.config import Settings
from app.storage.base import StorageProvider


def create_storage_provider(settings: Settings) -> StorageProvider:
    provider = settings.storage_provider
    if provider == "local":
        from app.storage.local import LocalJsonStorageProvider

        return LocalJsonStorageProvider(settings.data_dir)
    if provider == "azure_blob":
        from app.storage.azure_blob import AzureBlobStorageProvider

        return AzureBlobStorageProvider(
            container=settings.azure_container,
            account_url=settings.azure_account_url,
            connection_string=settings.azure_connection_string,
        )
    raise ValueError(f"Unknown STORAGE_PROVIDER '{provider}'. Use 'local' or 'azure_blob'.")
