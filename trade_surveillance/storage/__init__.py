"""Supabase Storage client for ML pipeline artefacts."""

from trade_surveillance.storage.supabase_storage import download_bytes, upload_bytes

__all__ = ["upload_bytes", "download_bytes"]
