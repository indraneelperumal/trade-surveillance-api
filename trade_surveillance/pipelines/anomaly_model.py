"""
Anomaly Detection Pipeline v2 — Supabase-native.

Replaces the original anomaly_model.py (which read/wrote via AWS S3).
This version reads features.parquet from Supabase Storage, trains an
IsolationForest, runs SHAP on flagged trades, classifies anomaly types by rule,
then writes results directly to Supabase PostgreSQL:

  • ~16,000 rows  →  alerts table     (one alert per flagged trade)
  •      1 row    →  model_runs table  (run lineage + metrics)
  • model.pkl + medians.json  →  Supabase Storage  (for future re-scoring)

Run:
    python -m trade_surveillance.pipelines.anomaly_model_v2

Prerequisites:
    pip install -e ".[dev,pipelines]"
    feature_engineering_v2.py must have run successfully first.
    .env must have: DATABASE_URL, SUPABASE_URL,
                    SUPABASE_SERVICE_ROLE_KEY, SUPABASE_STORAGE_BUCKET

──────────────────────────────────────────────────────────────────────────
UNCHANGED from original anomaly_model.py (pure ML — no I/O dependencies):
  prepare_features(), inject_anomalies(), build_feature_matrix(),
  train_model(), score_trades(), run_shap(), classify_anomaly_type(),
  validate_recall()

CHANGED (I/O boundaries + DB writes):
  load_features()         — S3 download  → Supabase Storage download
  upload_artifacts()      — S3 upload    → Supabase Storage upload
  write_alerts_to_db()    — NEW: batch INSERT into alerts table
  write_model_run_to_db() — NEW: INSERT into model_runs table
  main()                  — removes require_aws_profile(), wires new I/O
──────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import io
import json
import pickle
import random
import time
import uuid
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import shap
from sklearn.ensemble import IsolationForest
from sqlalchemy import text

from trade_surveillance.config import get_settings
from trade_surveillance.db.migrator import get_engine
from trade_surveillance.storage import download_bytes, upload_bytes

# ── Must exactly match feature_engineering_v2.FEATURE_COLS ───────────────────
FEATURE_COLS: list[str] = [
    "price_vs_nbbo_bps",
    "adv_pct",
    "is_off_hours",
    "is_otc",
    "depth_imbalance",
    "z_score_price",
    "z_score_volume",
    "trader_buy_sell_ratio",
    "trader_volume_share",
    "counterparty_daily_count",
    "return_vs_prev",
    "trade_value_pct_risk_limit",
]

# Anomaly type → alert severity (used when writing to the alerts table)
_SEVERITY_MAP: dict[str, str] = {
    "fat_finger":  "HIGH",
    "spoofing":    "HIGH",
    "multi_flag":  "HIGH",
    "volume_spike": "MEDIUM",
    "wash_trade":   "MEDIUM",
    "off_hours": "LOW",
    "unknown":   "LOW",
}

_ALERTS_BATCH_SIZE = 500  # rows per DB round-trip

_ALERTS_INSERT_SQL = text(
    """
    INSERT INTO alerts (
        id, trade_id,
        anomaly_score, anomaly_rank, anomaly_type,
        top_shap_feature, top_3_shap_features,
        feature_spec_version, model_features,
        scoring_model_run_id, scored_at, scoring_mode,
        severity, status
    ) VALUES (
        :id, :trade_id,
        :anomaly_score, :anomaly_rank, :anomaly_type,
        :top_shap_feature, :top_3_shap_features,
        :feature_spec_version, :model_features,
        :scoring_model_run_id, :scored_at, :scoring_mode,
        :severity, :status
    )
    ON CONFLICT (trade_id) DO NOTHING
    """
)

_MODEL_RUNS_INSERT_SQL = text(
    """
    INSERT INTO model_runs (
        id, run_type, model_name, model_version, status,
        parameters, metrics,
        total_records, flagged_count, recall,
        artifact_keys, runtime_seconds,
        started_at, completed_at
    ) VALUES (
        :id, :run_type, :model_name, :model_version, :status,
        :parameters, :metrics,
        :total_records, :flagged_count, :recall,
        :artifact_keys, :runtime_seconds,
        :started_at, :completed_at
    )
    """
)


# ─── STEP 1: LOAD FEATURES FROM SUPABASE STORAGE ─────────────────────────────

def load_features() -> pd.DataFrame:
    """
    Download features.parquet from Supabase Storage.

    Raises:
        ValueError: If required feature columns are missing — indicates
                    feature_engineering_v2.py needs to be re-run.
    """
    s = get_settings()
    print(f"      Downloading {s.storage_bucket}/{s.features_key} ...")

    data = download_bytes(s.storage_bucket, s.features_key)
    df   = pd.read_parquet(io.BytesIO(data))

    missing_features = [c for c in FEATURE_COLS if c not in df.columns]
    if missing_features:
        raise ValueError(
            f"features.parquet is missing required columns: {missing_features}\n"
            "Re-run feature_engineering_v2.py to regenerate."
        )
    if "trade_id" not in df.columns:
        raise ValueError(
            "features.parquet is missing 'trade_id' — cannot write alerts back to DB."
        )

    print(f"      Loaded {len(df):,} rows × {df.shape[1]} columns")
    return df


# ─── ML CORE — unchanged from original anomaly_model.py ──────────────────────

def prepare_features(df: pd.DataFrame) -> tuple[np.ndarray, dict]:
    """Build feature matrix X and per-column medians for NaN imputation."""
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
    """
    Inject 50 synthetic anomalies with known types to measure recall.
    Synthetics are excluded from DB writes — used for QA only.

    Updated to use current FEATURE_COLS (no spread / relative_spread /
    inter_arrival_time from the original version).
    """
    rng = random.Random(42)
    df  = df.copy()
    df["injected"]      = False
    df["injected_type"] = None
    injections = []
    n_real = len(df)

    # Fat finger: extreme price deviation + execution far from NBBO
    for i in range(20):
        row = df.iloc[rng.randint(0, n_real - 1)].copy()
        row["trade_id"]          = f"SYNTHETIC_{i}"
        row["z_score_price"]     = rng.uniform(10, 15)
        row["price_vs_nbbo_bps"] = rng.uniform(300, 600)
        row["return_vs_prev"]    = rng.uniform(0.08, 0.15)
        row["injected"]          = True
        row["injected_type"]     = "fat_finger"
        injections.append(row)

    # Volume spike: abnormally large trade + high trader concentration
    for i in range(20, 40):
        row = df.iloc[rng.randint(0, n_real - 1)].copy()
        row["trade_id"]               = f"SYNTHETIC_{i}"
        row["z_score_volume"]         = rng.uniform(10, 20)
        row["trader_volume_share"]    = rng.uniform(0.70, 0.95)
        row["trader_buy_sell_ratio"]  = rng.uniform(0.92, 1.00)
        row["adv_pct"]                = rng.uniform(0.15, 0.25)
        row["injected"]               = True
        row["injected_type"]          = "volume_spike"
        injections.append(row)

    # Off-hours spoofing: forced off-hours + heavily skewed order book
    for i in range(40, 50):
        row = df.iloc[rng.randint(0, n_real - 1)].copy()
        row["trade_id"]        = f"SYNTHETIC_{i}"
        row["is_off_hours"]    = 1
        row["depth_imbalance"] = rng.uniform(0.92, 0.999)
        row["z_score_volume"]  = rng.uniform(5, 8)
        row["injected"]        = True
        row["injected_type"]   = "off_hours_spoofing"
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
    t0    = time.time()
    model = IsolationForest(
        n_estimators=200,
        contamination=0.08,
        max_samples="auto",
        random_state=42,
    )
    model.fit(X)
    print(f"      Training complete in {time.time() - t0:.1f}s")
    return model


def score_trades(
    model: IsolationForest, X: np.ndarray, df: pd.DataFrame
) -> pd.DataFrame:
    df = df.copy()
    scores = model.decision_function(X)
    preds  = model.predict(X)

    df["anomaly_score"] = scores
    df["is_anomaly"]    = preds == -1
    df["anomaly_rank"]  = (
        pd.Series(scores, index=df.index)
        .rank(ascending=True, method="average")
        .values
    )

    n_flagged = int(df["is_anomaly"].sum())
    print(f"      Flagged: {n_flagged:,} ({n_flagged / len(df) * 100:.1f}%)")
    return df


def run_shap(
    model: IsolationForest, X: np.ndarray, df: pd.DataFrame
) -> pd.DataFrame:
    """
    Run SHAP TreeExplainer on flagged trades only.
    Stores top_shap_feature (str) and top_3_shap_features (JSON string)
    on each flagged row for later insertion into the alerts table.
    """
    df = df.copy()
    df["top_3_shap_features"] = None
    df["top_shap_feature"]    = None

    flagged_mask = df["is_anomaly"].values
    n_flagged    = int(flagged_mask.sum())

    if n_flagged == 0:
        warnings.warn("No flagged trades — skipping SHAP.")
        return df

    print(f"      Running SHAP on {n_flagged:,} flagged trades ...")
    flagged_pos = np.where(flagged_mask)[0]
    X_flagged   = X[flagged_pos]

    explainer = shap.TreeExplainer(model)
    shap_vals = explainer.shap_values(X_flagged)
    if isinstance(shap_vals, list):
        shap_vals = shap_vals[0]

    top3_json  = []
    top1_names = []
    for row_shap in shap_vals:
        order = np.argsort(np.abs(row_shap))[::-1]
        top3  = [[FEATURE_COLS[j], round(float(row_shap[j]), 6)] for j in order[:3]]
        top3_json.append(json.dumps(top3))
        top1_names.append(FEATURE_COLS[order[0]])

    df.loc[flagged_pos, "top_3_shap_features"] = np.array(top3_json,  dtype=object)
    df.loc[flagged_pos, "top_shap_feature"]    = np.array(top1_names, dtype=object)
    return df


def classify_anomaly_type(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rule-based classification applied only to model-flagged trades.

    Spoofing note: depth_imbalance measures order-book state at execution
    time (we have no order-cancel event data). Alerts of type 'spoofing'
    represent an order-book imbalance pattern — a lead for investigation,
    not a confirmed spoofing act.
    """
    df = df.copy()
    df["anomaly_type"] = None

    anomaly_mask = df["is_anomaly"]
    if anomaly_mask.sum() == 0:
        warnings.warn("No anomalies to classify.")
        return df

    fat_finger   = df["z_score_price"]  > 4
    volume_spike = df["z_score_volume"] > 4
    off_hours    = df["is_off_hours"].astype(bool)
    spoofing     = df["depth_imbalance"].abs() > 0.8
    wash_trade   = (df["trader_buy_sell_ratio"] > 0.9) & (df["z_score_volume"] > 2)

    n_matched = (
        fat_finger.astype(int)   + volume_spike.astype(int) +
        off_hours.astype(int)    + spoofing.astype(int) +
        wash_trade.astype(int)
    )

    df.loc[anomaly_mask & (n_matched > 1),                         "anomaly_type"] = "multi_flag"
    df.loc[anomaly_mask & (n_matched == 1) & fat_finger,           "anomaly_type"] = "fat_finger"
    df.loc[anomaly_mask & (n_matched == 1) & volume_spike,         "anomaly_type"] = "volume_spike"
    df.loc[anomaly_mask & (n_matched == 1) & off_hours,            "anomaly_type"] = "off_hours"
    df.loc[anomaly_mask & (n_matched == 1) & spoofing,             "anomaly_type"] = "spoofing"
    df.loc[anomaly_mask & (n_matched == 1) & wash_trade,           "anomaly_type"] = "wash_trade"
    df.loc[anomaly_mask & (n_matched == 0),                        "anomaly_type"] = "unknown"
    return df


def validate_recall(df: pd.DataFrame) -> dict:
    """Print synthetic recall breakdown and return metrics dict."""
    injected = df[df["injected"]]
    n_caught = int(injected["is_anomaly"].sum())
    n_total  = len(injected)
    print("\n  ── Synthetic Recall Validation ──")
    print(f"  Overall: {n_caught}/{n_total} ({n_caught / n_total * 100:.1f}%)")
    for itype in sorted(injected["injected_type"].dropna().unique()):
        sub   = injected[injected["injected_type"] == itype]
        n_hit = int(sub["is_anomaly"].sum())
        n_sub = len(sub)
        print(f"    {itype:<25} {n_hit}/{n_sub} ({n_hit / n_sub * 100:.1f}%)")
    return {"synthetic_caught": n_caught, "synthetic_total": n_total}


# ─── STEP 5a: UPLOAD ARTIFACTS TO SUPABASE STORAGE ───────────────────────────

def upload_artifacts(model: IsolationForest, medians: dict) -> dict:
    """
    Upload trained model (.pkl) and feature medians (.json) to Storage.

    Returns:
        Dict of storage paths for inclusion in the model_runs record.
    """
    s = get_settings()

    model_bytes = pickle.dumps(model)
    upload_bytes(s.storage_bucket, s.model_key, model_bytes)
    print(
        f"      Model   → {s.storage_bucket}/{s.model_key}"
        f"  ({len(model_bytes) / 1024:.0f} KB)"
    )

    medians_bytes = json.dumps(medians, indent=2).encode("utf-8")
    upload_bytes(s.storage_bucket, s.medians_key, medians_bytes)
    print(f"      Medians → {s.storage_bucket}/{s.medians_key}")

    return {
        "model_key":   s.model_key,
        "medians_key": s.medians_key,
        "features_key": s.features_key,
    }


# ─── STEP 5b: WRITE ALERTS TO DB ─────────────────────────────────────────────

def write_alerts_to_db(df_anomalies: pd.DataFrame, model_run_id: str) -> int:
    """
    Batch-INSERT flagged trades into the alerts table.

    Idempotent — ON CONFLICT (trade_id) DO NOTHING means safe to re-run.
    Inserts in batches of _ALERTS_BATCH_SIZE to avoid oversized transactions.

    Args:
        df_anomalies: Rows where is_anomaly=True and injected=False.
        model_run_id: UUID string of the parent model_runs row.

    Returns:
        Number of rows submitted (duplicates silently skipped by the DB).
    """
    if df_anomalies.empty:
        warnings.warn("No anomaly rows to insert — alerts table unchanged.")
        return 0

    engine    = get_engine()
    scored_at = datetime.now(timezone.utc).isoformat()

    # to_dict("records") is C-optimised — far faster than iterrows() at 16k rows
    records = df_anomalies.to_dict("records")
    rows: list[dict] = []

    for rec in records:
        # top_3_shap_features is stored as a JSON string in the DataFrame;
        # parse it back to a Python list before inserting so psycopg3 can
        # serialise it correctly for the JSONB column.
        raw_top3 = rec.get("top_3_shap_features")
        top3_parsed = json.loads(raw_top3) if raw_top3 is not None else None

        # Capture raw feature values for analyst review in the alert detail UI.
        # We pass json.dumps() strings here because we use raw SQL text() —
        # psycopg3 does not auto-cast Python dicts to JSONB in that mode.
        model_features = {
            col: (
                None
                if rec[col] is None or (isinstance(rec[col], float) and np.isnan(rec[col]))
                else round(float(rec[col]), 6)
            )
            for col in FEATURE_COLS
        }

        # trade_id may arrive as a bytes object (16-byte binary UUID) if the
        # Parquet was written before the str() cast was added to load_from_db.
        # Decode it properly so psycopg3 receives a valid UUID string.
        raw_tid = rec["trade_id"]
        if isinstance(raw_tid, (bytes, bytearray)):
            trade_id_str = str(uuid.UUID(bytes=bytes(raw_tid)))
        else:
            trade_id_str = str(raw_tid)

        anomaly_type = rec["anomaly_type"] or "unknown"
        rows.append({
            "id":                    str(uuid.uuid4()),
            "trade_id":              trade_id_str,
            "anomaly_score":         float(rec["anomaly_score"]),
            # anomaly_rank is a float (pandas rank uses average method);
            # round before int to avoid silent truncation of 0.5 values.
            "anomaly_rank":          int(round(float(rec["anomaly_rank"]))),
            "anomaly_type":          anomaly_type,
            "top_shap_feature":      rec.get("top_shap_feature"),
            "top_3_shap_features":   json.dumps(top3_parsed),
            "feature_spec_version":  "v1",
            "model_features":        json.dumps(model_features),
            "scoring_model_run_id":  model_run_id,
            "scored_at":             scored_at,
            "scoring_mode":          "batch_isolation_forest_v2",
            "severity":              _SEVERITY_MAP.get(anomaly_type, "LOW"),
            "status":                "OPEN",
        })

    written = 0
    with engine.begin() as conn:
        for start in range(0, len(rows), _ALERTS_BATCH_SIZE):
            batch = rows[start : start + _ALERTS_BATCH_SIZE]
            conn.execute(_ALERTS_INSERT_SQL, batch)
            written += len(batch)
            print(f"      Inserted {written:,} / {len(rows):,} alerts ...")

    return written


# ─── STEP 5c: WRITE MODEL RUN TO DB ──────────────────────────────────────────

def write_model_run_to_db(
    *,
    model_run_id: str,
    total_records: int,
    flagged_count: int,
    recall_metrics: dict,
    artifact_keys: dict,
    runtime_seconds: float,
    started_at: datetime,
) -> None:
    """Insert one row into model_runs to track this pipeline execution."""
    engine       = get_engine()
    completed_at = datetime.now(timezone.utc)
    flagged_pct  = (
        round(flagged_count / total_records * 100, 2) if total_records else 0.0
    )
    synthetic_recall = (
        round(
            recall_metrics["synthetic_caught"] / recall_metrics["synthetic_total"] * 100, 1
        )
        if recall_metrics["synthetic_total"]
        else 0.0
    )

    with engine.begin() as conn:
        conn.execute(
            _MODEL_RUNS_INSERT_SQL,
            {
                "id":           model_run_id,
                "run_type":     "batch_scoring",
                "model_name":   "IsolationForest",
                "model_version": "2.0",
                "status":       "COMPLETED",
                "parameters": json.dumps({
                    "n_estimators":          200,
                    "contamination":         0.08,
                    "random_state":          42,
                    "feature_cols":          FEATURE_COLS,
                    "feature_spec_version":  "v1",
                }),
                "metrics": json.dumps({
                    "flagged_pct":            flagged_pct,
                    "synthetic_recall_pct":   synthetic_recall,
                }),
                "total_records":    total_records,
                "flagged_count":    flagged_count,
                "recall":           synthetic_recall / 100,
                "artifact_keys":    json.dumps(artifact_keys),
                "runtime_seconds":  round(runtime_seconds, 2),
                "started_at":       started_at.isoformat(),
                "completed_at":     completed_at.isoformat(),
            },
        )
    print(f"      model_runs row written  (id={model_run_id})")


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 64)
    print("  trade_surveillance.pipelines.anomaly_model_v2")
    print("=" * 64)

    s            = get_settings()
    model_run_id = str(uuid.uuid4())
    started_at   = datetime.now(timezone.utc)
    t0_wall      = time.time()

    print(f"\n  Features source : {s.storage_bucket}/{s.features_key}")
    print(f"  Model output    : {s.storage_bucket}/{s.model_key}")
    print(f"  Model run ID    : {model_run_id}")
    print()

    print("[1/8] Loading features from Supabase Storage ...")
    df = load_features()

    print("\n[2/8] Preparing feature matrix + medians ...")
    _, medians = prepare_features(df)
    print(f"      Medians computed on {len(df):,} rows")

    print("\n[3/8] Injecting 50 synthetic anomalies for recall validation ...")
    df = inject_anomalies(df)

    print("\n[4/8] Building feature matrix & training IsolationForest ...")
    X_full = build_feature_matrix(df, medians)
    model  = train_model(X_full)

    print("\n[5/8] Scoring all trades ...")
    df = score_trades(model, X_full, df)

    print("\n[6/8] Running SHAP on flagged trades ...")
    df = run_shap(model, X_full, df)

    print("\n[7/8] Classifying anomaly types ...")
    df = classify_anomaly_type(df)
    recall_metrics = validate_recall(df)

    # Strip injected synthetics — never written to the DB
    df_real      = df[~df["injected"]].copy().reset_index(drop=True)
    df_anomalies = df_real[df_real["is_anomaly"]].copy()

    n_total   = len(df_real)
    n_flagged = len(df_anomalies)
    runtime   = time.time() - t0_wall

    print("\n[8/8] Writing results to Supabase ...")
    artifact_keys = upload_artifacts(model, medians)
    # model_runs row must exist before alerts — alerts.scoring_model_run_id is a FK
    write_model_run_to_db(
        model_run_id=model_run_id,
        total_records=n_total,
        flagged_count=n_flagged,
        recall_metrics=recall_metrics,
        artifact_keys=artifact_keys,
        runtime_seconds=runtime,
        started_at=started_at,
    )
    n_written = write_alerts_to_db(df_anomalies, model_run_id)

    # Final summary
    type_counts = df_anomalies["anomaly_type"].value_counts()
    print("\n" + "─" * 64)
    print(f"  Total trades scored  : {n_total:>10,}")
    print(f"  Alerts written to DB : {n_written:>10,}  ({n_flagged / n_total * 100:.1f}%)")
    print(f"  Synthetic recall     : {recall_metrics['synthetic_caught']:>10}/50")
    print(f"  Runtime              : {runtime:>10.1f}s")
    print("─" * 64)
    print("  Anomaly type breakdown:")
    for atype in [
        "fat_finger", "volume_spike", "off_hours",
        "spoofing", "wash_trade", "multi_flag", "unknown",
    ]:
        print(f"    {atype:<22}  {type_counts.get(atype, 0):>6,}")
    print("─" * 64)
    print("\nDone.\n")


if __name__ == "__main__":
    main()
