import collections
import io
import json
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from tqdm import tqdm

from trade_surveillance.aws.s3 import make_s3_client, upload_bytes_atomic
from trade_surveillance.config import get_settings, require_aws_profile

_bad_lines: collections.deque = collections.deque()  # thread-safe append


def list_s3_keys(s3_client, bucket: str, prefix: str) -> list:
    keys = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".json"):
                keys.append(key)
    if not keys:
        raise ValueError(f"No .json keys found under s3://{bucket}/{prefix}")
    return keys


def download_and_parse(s3_client, bucket: str, key: str) -> list:
    records = []
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        raw = response["Body"].read().decode("utf-8")
    except Exception as exc:
        warnings.warn(f"Failed to download {key}: {exc}")
        return records

    for line_no, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            _bad_lines.append((key, line_no, str(exc)))
            warnings.warn(f"Bad JSON in {key} line {line_no}: {exc}")
    return records


def load_raw_data(profile: str) -> pd.DataFrame:
    s = get_settings()
    print("\n[1/4] Listing S3 keys ...")
    s3 = make_s3_client(profile, max_pool_connections=32)
    keys = list_s3_keys(s3, s.s3_bucket, s.raw_prefix)
    print(f"      Found {len(keys):,} .json files")

    print(f"[2/4] Downloading & parsing ({len(keys):,} files, 32 workers) ...")
    all_records = []
    zero_record_files = 0

    with ThreadPoolExecutor(max_workers=32) as pool:
        futures = {pool.submit(download_and_parse, s3, s.s3_bucket, k): k for k in keys}
        for future in tqdm(as_completed(futures), total=len(futures), unit="file"):
            result = future.result()
            if result:
                all_records.extend(result)
            else:
                zero_record_files += 1

    if zero_record_files:
        warnings.warn(f"{zero_record_files} files returned zero valid records")
    if _bad_lines:
        warnings.warn(f"{len(_bad_lines)} total bad JSON lines skipped")

    print(f"      Parsed {len(all_records):,} records total")
    df = pd.DataFrame(all_records)

    if len(df) < 100_000:
        warnings.warn(
            f"Only {len(df):,} rows loaded — expected at least 100,000. "
            "Check for S3 access issues or data loss."
        )

    for col in ("symbol", "exchange", "side", "order_type"):
        if col in df.columns:
            df[col] = df[col].astype("category")

    return df


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    print("[3/4] Engineering features ...")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["date"] = df["timestamp"].dt.date

    df["spread"] = df["ask_price"] - df["bid_price"]
    df["mid_price"] = (df["bid_price"] + df["ask_price"]) / 2
    df["relative_spread"] = df["spread"] / df["mid_price"]

    size_sum = df["bid_size"] + df["ask_size"]
    df["depth_imbalance"] = (df["bid_size"] - df["ask_size"]) / size_sum

    grp = df.groupby(["symbol", "date"], observed=True)
    df["z_score_price"] = grp["price"].transform(
        lambda x: (x - x.mean()) / x.std(ddof=1)
    )
    df["z_score_volume"] = grp["volume"].transform(
        lambda x: (x - x.mean()) / x.std(ddof=1)
    )

    total_vol = df.groupby(["symbol", "date"], observed=True)["volume"].transform("sum")
    df["trader_volume_share"] = df["volume"] / total_vol

    eastern = df["timestamp"].dt.tz_convert("US/Eastern")
    hour = eastern.dt.hour
    minute = eastern.dt.minute
    df["is_off_hours"] = (hour < 9) | ((hour == 9) & (minute < 30)) | (hour >= 16)

    df["is_otc"] = df["exchange"] == "OTC"

    df = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    df["inter_arrival_time"] = (
        df.groupby("symbol", observed=True)["timestamp"]
        .diff()
        .dt.total_seconds()
    )

    prev_price = df.groupby("symbol", observed=True)["price"].shift(1)
    df["return_vs_prev"] = np.where(
        (prev_price > 0) & (df["price"] > 0),
        np.log(df["price"] / prev_price),
        np.nan,
    )

    known_sides = {"Buy", "Sell"}
    unexpected = df[~df["side"].isin(known_sides)]
    if len(unexpected) > 0:
        warnings.warn(
            f"{len(unexpected):,} rows have unexpected side values: "
            f"{unexpected['side'].unique().tolist()}"
        )

    valid = df[df["side"].isin(known_sides)].copy()
    valid["date_"] = valid["date"]
    buy_counts = (
        valid[valid["side"] == "Buy"]
        .groupby(["trader_id", "date_"])
        .size()
        .rename("buy_count")
    )
    total_counts = (
        valid.groupby(["trader_id", "date_"])
        .size()
        .rename("total_count")
    )
    ratio = (
        buy_counts.reindex(total_counts.index).fillna(0) / total_counts
    ).rename("trader_buy_sell_ratio")
    ratio_df = ratio.reset_index().rename(columns={"date_": "date"})

    df = df.merge(ratio_df, on=["trader_id", "date"], how="left")

    print(f"      Features complete — DataFrame shape: {df.shape}")
    return df


def write_features(df: pd.DataFrame, profile: str) -> None:
    print("[4/4] Writing features.parquet to S3 ...")
    s = get_settings()
    s3 = make_s3_client(profile, max_pool_connections=32)

    table = pa.Table.from_pandas(df)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    size_mb = buf.tell() / 1_048_576
    buf.seek(0)
    data = buf.read()
    upload_bytes_atomic(s3, s.s3_bucket, s.features_key, data)

    print(f"      Written: s3://{s.s3_bucket}/{s.features_key}")
    print(f"      Rows: {len(df):,}  |  Size: {size_mb:.1f} MB  |  Compression: snappy")


def main() -> None:
    print("=" * 60)
    print("  trade_surveillance.pipelines.feature_engineering")
    print("=" * 60)

    profile = require_aws_profile()
    s = get_settings()
    print(f"  Source      : s3://{s.s3_bucket}/{s.raw_prefix}")
    print(f"  Output      : s3://{s.s3_bucket}/{s.features_key}")

    df = load_raw_data(profile)
    df = engineer_features(df)
    write_features(df, profile)

    print("\nDone.")


if __name__ == "__main__":
    main()
