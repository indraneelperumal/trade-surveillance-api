import os

import pytest

from trade_surveillance.config import Settings, clear_settings_cache, get_settings


@pytest.fixture(autouse=True)
def _clear_settings():
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_settings_defaults(monkeypatch):
    for key in list(os.environ):
        if key.startswith("TSP_"):
            monkeypatch.delenv(key, raising=False)
    clear_settings_cache()
    s = get_settings()
    assert isinstance(s, Settings)
    assert s.s3_bucket == "trade-surveillance-bucket"
    assert s.raw_prefix == "raw/"
    assert s.features_key == "features/features.parquet"
    assert s.anomalies_key == "processed/anomalies.parquet"
    assert s.memos_prefix == "memos"


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("TSP_S3_BUCKET", "my-test-bucket")
    clear_settings_cache()
    s = get_settings()
    assert s.s3_bucket == "my-test-bucket"
