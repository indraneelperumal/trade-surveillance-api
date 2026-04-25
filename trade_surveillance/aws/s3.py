"""Shared S3 client helpers (used by pipelines, agents, and optional scripts)."""

from __future__ import annotations

import io
import warnings
from uuid import uuid4

import boto3
import pandas as pd
from botocore.config import Config


def make_s3_client(profile: str, *, max_pool_connections: int = 10):
    session = boto3.Session(profile_name=profile)
    return session.client(
        "s3",
        config=Config(
            max_pool_connections=max_pool_connections,
            retries={"max_attempts": 5, "mode": "adaptive"},
        ),
    )


def download_parquet(s3_client, bucket: str, key: str) -> pd.DataFrame:
    buf = io.BytesIO()
    s3_client.download_fileobj(bucket, key, buf)
    buf.seek(0)
    return pd.read_parquet(buf)


def upload_bytes_atomic(s3_client, bucket: str, final_key: str, data: bytes) -> None:
    """Upload via temp key + copy_object for safer overwrites."""
    prefix, _, fname = final_key.rpartition("/")
    tmp_key = f"{prefix}/tmp_{uuid4()}_{fname}" if prefix else f"tmp_{uuid4()}_{fname}"
    try:
        s3_client.put_object(Bucket=bucket, Key=tmp_key, Body=data)
        s3_client.copy_object(
            Bucket=bucket,
            CopySource={"Bucket": bucket, "Key": tmp_key},
            Key=final_key,
        )
        s3_client.delete_object(Bucket=bucket, Key=tmp_key)
    except Exception:
        try:
            s3_client.delete_object(Bucket=bucket, Key=tmp_key)
        except Exception as cleanup_exc:
            warnings.warn(f"Failed to delete temp key {tmp_key}: {cleanup_exc}")
        raise
