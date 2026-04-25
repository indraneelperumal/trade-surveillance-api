import io
import json
import pickle
import random
import time
import warnings

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import shap
from sklearn.ensemble import IsolationForest

from trade_surveillance.aws.s3 import download_parquet, make_s3_client, upload_bytes_atomic
from trade_surveillance.config import get_settings, require_aws_profile

FEATURE_COLS = [
    "spread", "mid_price", "relative_spread", "depth_imbalance",
    "z_score_price", "z_score_volume", "trader_volume_share",
    "is_off_hours", "is_otc", "inter_arrival_time",
    "return_vs_prev", "trader_buy_sell_ratio",
]


def load_features(profile: str) -> pd.DataFrame:
    s = get_settings()
    s3 = make_s3_client(profile)
    df = download_parquet(s3, s.s3_bucket, s.features_key)
    if df.shape[0] < 100_000 or df.shape[1] < 32:
        raise ValueError(f"Unexpected shape {df.shape} — expected (≥100000, ≥32)")
    print(f"      Loaded {len(df):,} rows × {df.shape[1]} columns")
    return df


def prepare_features(df: pd.DataFrame) -> tuple:
    feat = df[FEATURE_COLS].copy()
    for col in ("is_off_hours", "is_otc"):
        feat[col] = feat[col].astype(int)
    medians = {col: float(feat[col].median()) for col in FEATURE_COLS}
    X = feat.fillna(medians).values.astype(np.float64)
    nan_cols = [c for c in FEATURE_COLS if feat[c].isna().any()]
    if nan_cols:
        print(f"      NaN-filled columns: {nan_cols}")
    return X, medians


def inject_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    rng = random.Random(42)
    df = df.copy()
    df["injected"] = False
    df["injected_type"] = None

    injections = []
    n_real = len(df)

    spread_max = float(df["spread"].max())

    for i in range(20):
        row = df.iloc[rng.randint(0, n_real - 1)].copy()
        row["trade_id"] = f"SYNTHETIC_{i}"
        row["z_score_price"] = rng.uniform(10, 15)
        row["spread"] = spread_max * rng.uniform(2, 4)
        row["relative_spread"] = rng.uniform(0.15, 0.25)
        row["injected"] = True
        row["injected_type"] = "fat_finger"
        injections.append(row)

    for i in range(20, 40):
        row = df.iloc[rng.randint(0, n_real - 1)].copy()
        row["trade_id"] = f"SYNTHETIC_{i}"
        row["z_score_volume"] = rng.uniform(10, 20)
        row["trader_volume_share"] = rng.uniform(0.7, 0.95)
        row["trader_buy_sell_ratio"] = rng.uniform(0.92, 1.0)
        row["injected"] = True
        row["injected_type"] = "volume_spike"
        injections.append(row)

    for i in range(40, 50):
        row = df.iloc[rng.randint(0, n_real - 1)].copy()
        row["trade_id"] = f"SYNTHETIC_{i}"
        row["is_off_hours"] = 1
        row["depth_imbalance"] = rng.uniform(0.92, 0.999)
        row["z_score_volume"] = rng.uniform(5, 8)
        row["injected"] = True
        row["injected_type"] = "off_hours_spoofing"
        injections.append(row)

    synth_df = pd.DataFrame(injections)
    df = pd.concat([df, synth_df], ignore_index=True)
    print(f"      Real: {n_real:,}  |  Injected: 50  |  Total: {len(df):,}")
    return df


def build_feature_matrix(df: pd.DataFrame, medians: dict) -> np.ndarray:
    feat = df[FEATURE_COLS].copy()
    for col in ("is_off_hours", "is_otc"):
        feat[col] = feat[col].astype(int)
    return feat.fillna(medians).values.astype(np.float64)


def train_model(X: np.ndarray) -> IsolationForest:
    t0 = time.time()
    model = IsolationForest(
        n_estimators=200,
        contamination=0.08,
        max_samples="auto",
        random_state=42,
    )
    model.fit(X)
    print(f"      Training complete in {time.time() - t0:.1f}s")
    return model


def score_trades(model: IsolationForest, X: np.ndarray, df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    scores = model.decision_function(X)
    preds = model.predict(X)

    df["anomaly_score"] = scores
    df["is_anomaly"] = preds == -1
    df["anomaly_rank"] = pd.Series(scores, index=df.index).rank(
        ascending=True, method="average"
    ).values

    n_flagged = df["is_anomaly"].sum()
    print(f"      Flagged: {n_flagged:,} ({n_flagged / len(df) * 100:.1f}%)")
    return df


def run_shap(model: IsolationForest, X: np.ndarray, df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["top_3_shap_features"] = None
    df["top_shap_feature"] = None

    flagged_mask = df["is_anomaly"].values
    n_flagged = int(flagged_mask.sum())

    if n_flagged == 0:
        warnings.warn("No flagged trades — skipping SHAP.")
        return df

    print(f"      Running SHAP on {n_flagged:,} flagged trades ...")
    flagged_pos = np.where(flagged_mask)[0]
    X_flagged = X[flagged_pos]

    explainer = shap.TreeExplainer(model)
    shap_vals = explainer.shap_values(X_flagged)
    if isinstance(shap_vals, list):
        shap_vals = shap_vals[0]

    top3_json = []
    top1_name = []
    for row_shap in shap_vals:
        order = np.argsort(np.abs(row_shap))[::-1]
        top3 = [[FEATURE_COLS[j], round(float(row_shap[j]), 6)] for j in order[:3]]
        top3_json.append(json.dumps(top3))
        top1_name.append(FEATURE_COLS[order[0]])

    df.loc[flagged_pos, "top_3_shap_features"] = np.array(top3_json, dtype=object)
    df.loc[flagged_pos, "top_shap_feature"] = np.array(top1_name, dtype=object)
    return df


def classify_anomaly_type(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["anomaly_type"] = None

    anomaly_mask = df["is_anomaly"]
    if anomaly_mask.sum() == 0:
        warnings.warn("No anomalies to classify.")
        return df

    fat_finger = df["z_score_price"] > 4
    volume_spike = df["z_score_volume"] > 4
    off_hours = df["is_off_hours"].astype(bool)
    spoofing = df["depth_imbalance"].abs() > 0.8
    wash_trade = (df["trader_buy_sell_ratio"] > 0.9) & (df["z_score_volume"] > 2)

    n_matched = (
        fat_finger.astype(int) + volume_spike.astype(int) +
        off_hours.astype(int) + spoofing.astype(int) +
        wash_trade.astype(int)
    )

    df.loc[anomaly_mask & (n_matched > 1), "anomaly_type"] = "multi_flag"
    df.loc[anomaly_mask & (n_matched == 1) & fat_finger, "anomaly_type"] = "fat_finger"
    df.loc[anomaly_mask & (n_matched == 1) & volume_spike, "anomaly_type"] = "volume_spike"
    df.loc[anomaly_mask & (n_matched == 1) & off_hours, "anomaly_type"] = "off_hours"
    df.loc[anomaly_mask & (n_matched == 1) & spoofing, "anomaly_type"] = "spoofing"
    df.loc[anomaly_mask & (n_matched == 1) & wash_trade, "anomaly_type"] = "wash_trade"
    df.loc[anomaly_mask & (n_matched == 0), "anomaly_type"] = "unknown"

    return df


def validate_recall(df: pd.DataFrame) -> None:
    injected = df[df["injected"]]
    n_caught = injected["is_anomaly"].sum()
    n_total = len(injected)
    print("\n  ── Synthetic Recall Validation ──")
    print(f"  Overall: {n_caught}/{n_total} ({n_caught / n_total * 100:.1f}%)")
    for itype in sorted(injected["injected_type"].dropna().unique()):
        sub = injected[injected["injected_type"] == itype]
        n_hit = sub["is_anomaly"].sum()
        n_sub = len(sub)
        print(f"    {itype:<22} {n_hit}/{n_sub} ({n_hit / n_sub * 100:.1f}%)")


def save_outputs(
    df_real: pd.DataFrame,
    model: IsolationForest,
    medians: dict,
    profile: str,
) -> None:
    s = get_settings()
    s3 = make_s3_client(profile)

    model_bytes = pickle.dumps(model)
    upload_bytes_atomic(s3, s.s3_bucket, s.model_key, model_bytes)
    print(f"      Model   → s3://{s.s3_bucket}/{s.model_key}  ({len(model_bytes) / 1024:.0f} KB)")

    medians_bytes = json.dumps(medians, indent=2).encode("utf-8")
    upload_bytes_atomic(s3, s.s3_bucket, s.medians_key, medians_bytes)
    print(f"      Medians → s3://{s.s3_bucket}/{s.medians_key}")

    table = pa.Table.from_pandas(df_real)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    size_mb = buf.tell() / 1_048_576
    buf.seek(0)
    upload_bytes_atomic(s3, s.s3_bucket, s.anomalies_key, buf.read())
    print(
        f"      Output  → s3://{s.s3_bucket}/{s.anomalies_key}  "
        f"({len(df_real):,} rows, {size_mb:.1f} MB)"
    )


def main() -> None:
    print("=" * 60)
    print("  trade_surveillance.pipelines.anomaly_model")
    print("=" * 60)

    profile = require_aws_profile()

    print("\n[1/8] Loading features ...")
    df = load_features(profile)

    print("\n[2/8] Preparing feature matrix + medians ...")
    _, medians = prepare_features(df)
    print(f"      Medians computed on {len(df):,} real rows")

    print("\n[3/8] Injecting 50 synthetic anomalies ...")
    df = inject_anomalies(df)

    print("\n[4/8] Building feature matrix & training IsolationForest ...")
    X_full = build_feature_matrix(df, medians)
    model = train_model(X_full)

    print("\n[5/8] Scoring all trades ...")
    df = score_trades(model, X_full, df)

    print("\n[6/8] Running SHAP on flagged trades ...")
    df = run_shap(model, X_full, df)

    print("\n[7/8] Classifying anomaly types ...")
    df = classify_anomaly_type(df)

    validate_recall(df)

    print("\n[8/8] Saving outputs to S3 ...")
    df_real = df[~df["injected"]].copy().reset_index(drop=True)
    df_real["anomaly_rank"] = df_real["anomaly_score"].rank(ascending=True, method="average")
    assert df_real.shape[1] == 40, f"Expected 40 columns, got {df_real.shape[1]}"
    save_outputs(df_real, model, medians, profile)

    n_total = len(df_real)
    n_anomaly = int(df_real["is_anomaly"].sum())
    n_caught = int(df[df["injected"]]["is_anomaly"].sum())
    type_counts = df_real[df_real["is_anomaly"]]["anomaly_type"].value_counts()

    print("\n" + "─" * 49)
    print(f"  Total trades scored:  {n_total:>10,}")
    print(f"  Anomalies flagged:    {n_anomaly:>10,} ({n_anomaly / n_total * 100:.1f}%)")
    print(f"  Synthetic recall:     {n_caught:>10}/50 ({n_caught / 50 * 100:.1f}%)")
    print("─" * 49)
    print("  Anomaly type breakdown:")
    for atype in ["fat_finger", "volume_spike", "off_hours", "spoofing",
                  "wash_trade", "multi_flag", "unknown"]:
        print(f"    {atype:<20} {type_counts.get(atype, 0):>6,}")
    print("─" * 49)
    print("\nDone.")


if __name__ == "__main__":
    main()
