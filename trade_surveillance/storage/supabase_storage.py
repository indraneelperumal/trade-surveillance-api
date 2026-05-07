"""
Supabase Storage client — replaces aws/s3.py for the ML pipeline layer.

Provides two primitives used by the pipeline:
  upload_bytes(bucket, path, data)   — upsert a file into Storage
  download_bytes(bucket, path)       — download a file from Storage

The Supabase service-role key is required for storage write access.
Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env before running
any pipeline step.
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from trade_surveillance.config import get_settings


@lru_cache(maxsize=1)
def _get_client() -> Client:
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_key:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env "
            "before running pipeline steps."
        )
    return create_client(s.supabase_url, s.supabase_service_key)


def upload_bytes(bucket: str, path: str, data: bytes) -> None:
    """
    Upload raw bytes to Supabase Storage at bucket/path.
    Overwrites if the file already exists (upsert).

    Args:
        bucket: Storage bucket name (e.g. "trade-surveillance-artifacts")
        path:   Object path inside the bucket (e.g. "features/features.parquet")
        data:   File contents as bytes
    """
    client = _get_client()
    client.storage.from_(bucket).upload(
        path=path,
        file=data,
        file_options={"content-type": "application/octet-stream", "upsert": "true"},
    )


def download_bytes(bucket: str, path: str) -> bytes:
    """
    Download a file from Supabase Storage and return its raw bytes.

    Args:
        bucket: Storage bucket name
        path:   Object path inside the bucket

    Returns:
        File contents as bytes.

    Raises:
        Exception if the file does not exist or the request fails.
    """
    client = _get_client()
    return client.storage.from_(bucket).download(path)
