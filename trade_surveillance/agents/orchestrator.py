"""
orchestrator.py — LangGraph multi-agent compliance investigation pipeline.

Entry point: investigate_trade(alert_id, auto_approve=True)

Graph flow:
  trade_context_node   — load alert + trade + engineered features from DB
       ↓
  market_context_node  — load ±60-min market window from DB
       ↓
  regulatory_screen_node — run deterministic rule-match on ML features
       ↓  (severity_router)
  [human_review_node]  — interrupt for HIGH severity (only if auto_approve=False)
       ↓
  compliance_memo_node — call Claude Sonnet, persist investigation to DB

All data is sourced exclusively from PostgreSQL.  No AWS dependencies.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
import warnings
from datetime import datetime, timezone
from typing import TypedDict

import anthropic
import pandas as pd
from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy import text

from trade_surveillance.agents.prompts import SYSTEM_PROMPT, build_user_prompt
from trade_surveillance.agents.tools_db import (
    compute_market_context,
    compute_trader_stats,
    load_alert_with_trade,
    load_market_window,
    load_trader_history,
)
from trade_surveillance.db.migrator import get_engine

logger = logging.getLogger(__name__)

# Read the model from env so it can be overridden on Render without a redeploy.
# Default: claude-3-5-sonnet-20241022 (widely available, verified working).
_ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")


# ── Graph state ───────────────────────────────────────────────────────────────

class TradeState(TypedDict, total=False):
    alert_id: str
    raw_trade: dict          # merged alert + trade + model_features
    anomaly_score: float
    anomaly_rank: float
    anomaly_type: str
    shap_features: list
    trader_history: dict
    market_context: dict
    rule_match: dict
    compliance_memo: dict
    verdict: str
    confidence: str
    error: str


# ── Node: trade_context ───────────────────────────────────────────────────────

def _make_trade_context_node():
    def trade_context_node(state: TradeState) -> dict:
        try:
            record = load_alert_with_trade(state["alert_id"])

            trader_id = record.get("trader_id")
            symbol = record.get("symbol")
            history_df = (
                load_trader_history(trader_id, symbol=symbol)
                if trader_id
                else pd.DataFrame()
            )
            stats = compute_trader_stats(history_df)

            # top_3_shap_features arrives as a Python list from JSONB.
            # Handle both list (DB) and JSON string (legacy) gracefully.
            shap_raw = record.get("top_3_shap_features")
            if shap_raw:
                try:
                    shap_features = (
                        json.loads(shap_raw)
                        if isinstance(shap_raw, str)
                        else shap_raw
                    )
                except (json.JSONDecodeError, TypeError):
                    shap_features = []
            else:
                shap_features = []

            return {
                "raw_trade": record,
                "trader_history": stats,
                "anomaly_score": float(record.get("anomaly_score") or 0),
                "anomaly_rank": float(record.get("anomaly_rank") or 0),
                "anomaly_type": str(record.get("anomaly_type") or "unknown"),
                "shap_features": shap_features,
            }
        except Exception as exc:
            return {"error": str(exc)}

    return trade_context_node


# ── Node: market_context ──────────────────────────────────────────────────────

def _make_market_context_node():
    def market_context_node(state: TradeState) -> dict:
        if state.get("error"):
            return {}
        try:
            raw = state.get("raw_trade", {})
            symbol = raw.get("symbol")
            ts_str = raw.get("timestamp")
            if not symbol or ts_str is None:
                return {"market_context": {}}

            ts = pd.Timestamp(ts_str)
            window_df = load_market_window(symbol, ts.to_pydatetime())
            context = compute_market_context(window_df, raw)
            return {"market_context": context}
        except Exception as exc:
            return {"error": str(exc)}

    return market_context_node


# ── Node: regulatory_screen ───────────────────────────────────────────────────
# Runs a deterministic rule match using the engineered ML features that are
# now present on raw_trade after tools_db merges model_features.

def _make_regulatory_screen_node():
    def regulatory_screen_node(state: TradeState) -> dict:
        if state.get("error"):
            return {}
        try:
            raw = state.get("raw_trade", {})

            # These keys now reliably exist because load_alert_with_trade
            # merges alerts.model_features into raw_trade.
            z_price = float(raw.get("z_score_price") or 0)
            z_vol   = float(raw.get("z_score_volume") or 0)
            off_hrs = bool(raw.get("is_off_hours", False))
            d_imb   = abs(float(raw.get("depth_imbalance") or 0))
            bsr     = float(raw.get("trader_buy_sell_ratio") or 0)

            matched: list[str] = []
            if z_price > 4:
                matched.append("FAT_FINGER")
            if z_vol > 4:
                matched.append("VOLUME_SPIKE")
            if off_hrs:
                matched.append("OFF_HOURS")
            if d_imb > 0.8:
                matched.append("SPOOFING")
            if bsr > 0.9 and z_vol > 2:
                matched.append("WASH_TRADE")

            if len(matched) >= 2 or "FAT_FINGER" in matched or "VOLUME_SPIKE" in matched:
                severity = "HIGH"
            elif "SPOOFING" in matched or "WASH_TRADE" in matched:
                severity = "MEDIUM"
            elif "OFF_HOURS" in matched:
                severity = "LOW"
            else:
                severity = "NONE"

            return {"rule_match": {"matched_rules": matched, "severity": severity}}
        except Exception as exc:
            return {"error": str(exc)}

    return regulatory_screen_node


# ── Node: human_review (interactive interrupt — skipped in auto_approve mode) ─

def human_review_node(state: TradeState) -> dict:
    raw = state.get("raw_trade", {})
    rm  = state.get("rule_match", {})
    th  = state.get("trader_history", {})
    print("\n" + "=" * 60)
    print("  HIGH SEVERITY TRADE — HUMAN REVIEW REQUIRED")
    print("=" * 60)
    print(f"  alert_id:     {state.get('alert_id')}")
    print(f"  symbol:       {raw.get('symbol')}")
    print(f"  trader_id:    {raw.get('trader_id')}")
    print(f"  anomaly_rank: {state.get('anomaly_rank')}")
    print(f"  anomaly_type: {state.get('anomaly_type')}")
    print(f"  rules:        {rm.get('matched_rules')}")
    print(f"  severity:     {rm.get('severity')}")
    print(f"  shap_features:{state.get('shap_features')}")
    if th:
        print(f"  trader stats: {th}")
    print("=" * 60)
    interrupt({"message": "HIGH severity trade — review findings above", "state": state})
    return {}


# ── Node: compliance_memo ─────────────────────────────────────────────────────

def _write_investigation_to_db(
    alert_id: str,
    memo: dict,
    *,
    model_version: str = _ANTHROPIC_MODEL,
    error_message: str | None = None,
) -> str:
    """
    Persist the compliance memo as a new investigations row.
    Returns the new investigation id (UUID string).

    Strategy:
    1. Try the full INSERT (includes model_version + error_message added in Phase 2
       migration). If the migration has run, this succeeds.
    2. If the full INSERT fails (e.g. columns not yet added on that DB), fall back
       to a minimal INSERT so the investigation is never silently lost.
    3. Alert status update runs in a SEPARATE transaction so it always commits
       even if step 1 or 2 had a rollback.
    """
    investigation_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    engine = get_engine()

    base_params = {
        "id":                  investigation_id,
        "alert_id":            alert_id,
        "verdict":             memo.get("verdict", "MONITOR"),
        "confidence":          memo.get("confidence", "LOW"),
        "rule_violated":       memo.get("rule_violated"),
        "summary":             memo.get("summary"),
        "evidence_points":     json.dumps(memo.get("evidence_points") or []),
        "recommended_action":  memo.get("recommended_action"),
        "data_gaps":           memo.get("data_gaps"),
        "memo_json":           json.dumps(memo),
        "now":                 now,
    }

    # ── Step 1: Full INSERT (with optional Phase 2 columns) ───────────────────
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO investigations (
                        id, alert_id, verdict, confidence, rule_violated,
                        summary, evidence_points, recommended_action, data_gaps,
                        memo_json, is_auto, model_version, error_message,
                        started_at, completed_at, created_at, updated_at
                    ) VALUES (
                        :id::uuid, :alert_id::uuid,
                        :verdict, :confidence, :rule_violated,
                        :summary, CAST(:evidence_points AS jsonb),
                        :recommended_action, :data_gaps,
                        CAST(:memo_json AS jsonb), TRUE,
                        :model_version, :error_message,
                        :now, :now, :now, :now
                    )
                """),
                {**base_params, "model_version": model_version, "error_message": error_message},
            )
    except Exception as primary_exc:
        # ── Step 2: Fallback INSERT without optional columns ──────────────────
        logger.warning(
            "Full investigation INSERT failed (%s) — retrying without optional columns. "
            "Run migrations to resolve permanently.",
            primary_exc,
        )
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO investigations (
                            id, alert_id, verdict, confidence, rule_violated,
                            summary, evidence_points, recommended_action, data_gaps,
                            memo_json, is_auto,
                            started_at, completed_at, created_at, updated_at
                        ) VALUES (
                            :id::uuid, :alert_id::uuid,
                            :verdict, :confidence, :rule_violated,
                            :summary, CAST(:evidence_points AS jsonb),
                            :recommended_action, :data_gaps,
                            CAST(:memo_json AS jsonb), TRUE,
                            :now, :now, :now, :now
                        )
                    """),
                    base_params,
                )
        except Exception as fallback_exc:
            logger.error(
                "Fallback investigation INSERT also failed for alert %s: %s",
                alert_id, fallback_exc,
            )
            # Store the exception so Step 3 (status update) still runs below.
            # We re-raise AFTER the status update so the alert is never stuck OPEN.
            _insert_exc: Exception | None = fallback_exc
        else:
            _insert_exc = None
    else:
        _insert_exc = None

    # ── Step 3: Alert status update (own transaction — always attempted) ──────
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE alerts
                    SET status = 'IN_PROGRESS', updated_at = :now
                    WHERE id = :alert_id::uuid
                      AND status = 'OPEN'
                """),
                {"alert_id": alert_id, "now": now},
            )
    except Exception as upd_exc:
        logger.warning("Alert status update failed for %s: %s", alert_id, upd_exc)

    if _insert_exc is not None:
        raise _insert_exc

    return investigation_id


def _make_compliance_memo_node():
    def compliance_memo_node(state: TradeState) -> dict:
        alert_id = state.get("alert_id", "UNKNOWN")

        # ── Error path: pipeline failed upstream ──────────────────────────────
        if state.get("error"):
            error_msg = state["error"]
            memo = {
                "summary": "Investigation could not complete due to a pipeline error.",
                "evidence_points": [
                    f"Pipeline error: {error_msg[:400]}",
                    "No trade or alert data was available to the LLM.",
                    "Re-run after resolving the error below.",
                ],
                "rule_violated": "NONE",
                "verdict": "MONITOR",
                "confidence": "LOW",
                "recommended_action": (
                    f"Review the pipeline error for alert {alert_id} "
                    "and re-trigger the investigation once data is confirmed present."
                ),
                "data_gaps": f"Full trade data unavailable. Error: {error_msg}",
            }
            try:
                _write_investigation_to_db(
                    alert_id, memo,
                    model_version="pipeline_error",
                    error_message=error_msg,
                )
            except Exception as db_exc:
                warnings.warn(f"Failed to persist error investigation: {db_exc}")
            return {"compliance_memo": memo, "verdict": "MONITOR", "confidence": "LOW"}

        # ── Happy path: call Claude Sonnet ────────────────────────────────────
        try:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY is not set.")

            client = anthropic.Anthropic(api_key=api_key)
            prompt = build_user_prompt(state)

            response = client.messages.create(
                model=_ANTHROPIC_MODEL,
                temperature=0,           # Deterministic — required for compliance
                max_tokens=1800,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = response.content[0].text.strip()

            # Strip markdown fences if Claude wraps the JSON
            if raw_text.startswith("```"):
                parts = raw_text.split("```")
                raw_text = parts[1] if len(parts) > 1 else raw_text
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
                raw_text = raw_text.strip()

            try:
                memo = json.loads(raw_text)
            except json.JSONDecodeError:
                warnings.warn(f"Claude returned non-JSON: {raw_text[:200]}")
                memo = {
                    "summary": "JSON parse error — raw response stored in memo_json.",
                    "evidence_points": [
                        raw_text[:400],
                        "Response was not valid JSON; check raw memo_json for full output.",
                        "Re-run investigation to obtain a structured result.",
                    ],
                    "rule_violated": "NONE",
                    "verdict": "MONITOR",
                    "confidence": "LOW",
                    "recommended_action": (
                        f"Re-run investigation for alert {alert_id} "
                        "after confirming model prompt integrity."
                    ),
                    "data_gaps": "Structured LLM response unavailable.",
                }

            # ── Hard-override verdict based on rule_match severity ────────────
            # This prevents Claude from over- or under-escalating.
            # Rule 8 in SYSTEM_PROMPT mirrors this, but we enforce it here too.
            severity = state.get("rule_match", {}).get("severity", "NONE")
            confidence = memo.get("confidence", "LOW")

            if severity == "HIGH" and confidence == "HIGH":
                memo["verdict"] = "ESCALATE"
            elif severity == "HIGH":
                memo["verdict"] = "MONITOR"
            elif severity == "MEDIUM":
                memo["verdict"] = "MONITOR"
            else:
                memo["verdict"] = "DISMISS"

            # ── Persist to database ───────────────────────────────────────────
            try:
                investigation_id = _write_investigation_to_db(
                    alert_id, memo, model_version=_ANTHROPIC_MODEL
                )
                memo["_investigation_id"] = investigation_id
            except Exception as db_exc:
                warnings.warn(f"Failed to persist investigation to DB: {db_exc}")

            return {
                "compliance_memo": memo,
                "verdict": memo["verdict"],
                "confidence": memo.get("confidence", "LOW"),
            }

        except Exception as exc:
            logger.error(
                "compliance_memo_node FAILED for alert %s: %s",
                alert_id, exc, exc_info=True,
            )
            error_msg = str(exc)
            error_memo = {
                "summary": "LLM call failed — investigation could not be completed.",
                "evidence_points": [
                    f"Error: {error_msg[:400]}",
                    "The Anthropic API call or JSON parsing failed.",
                    "Re-trigger investigation once the error is resolved.",
                ],
                "rule_violated": "NONE",
                "verdict": "MONITOR",
                "confidence": "LOW",
                "recommended_action": (
                    f"Re-trigger investigation for alert {alert_id} "
                    "after confirming the LLM API key and model name are correct."
                ),
                "data_gaps": f"LLM response unavailable. Error: {error_msg}",
            }
            try:
                _write_investigation_to_db(
                    alert_id, error_memo,
                    model_version="llm_error",
                    error_message=error_msg,
                )
            except Exception as db_exc:
                logger.error(
                    "Could not persist error investigation for alert %s: %s",
                    alert_id, db_exc,
                )
            return {"error": error_msg, "verdict": "MONITOR", "confidence": "LOW"}

    return compliance_memo_node


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_graph(auto_approve: bool = True):
    trade_context_node     = _make_trade_context_node()
    market_context_node    = _make_market_context_node()
    regulatory_screen_node = _make_regulatory_screen_node()
    compliance_memo_node   = _make_compliance_memo_node()

    def severity_router(state: TradeState) -> str:
        if state.get("error"):
            return "compliance_memo_node"
        severity = state.get("rule_match", {}).get("severity", "NONE")
        if severity == "HIGH" and not auto_approve:
            return "human_review_node"
        return "compliance_memo_node"

    graph = StateGraph(TradeState)
    graph.add_node("trade_context_node",     trade_context_node)
    graph.add_node("market_context_node",    market_context_node)
    graph.add_node("regulatory_screen_node", regulatory_screen_node)
    graph.add_node("compliance_memo_node",   compliance_memo_node)

    if not auto_approve:
        graph.add_node("human_review_node", human_review_node)
        graph.add_edge("human_review_node", "compliance_memo_node")

    graph.add_edge(START, "trade_context_node")
    graph.add_edge("trade_context_node",  "market_context_node")
    graph.add_edge("market_context_node", "regulatory_screen_node")
    graph.add_conditional_edges(
        "regulatory_screen_node",
        severity_router,
        {
            "human_review_node":   "human_review_node" if not auto_approve else "compliance_memo_node",
            "compliance_memo_node": "compliance_memo_node",
        },
    )
    graph.add_edge("compliance_memo_node", END)

    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


# ── Public entry point ────────────────────────────────────────────────────────

def investigate_trade(
    alert_id: str,
    *,
    auto_approve: bool = True,
) -> dict:
    """
    Run the compliance investigation pipeline for a given alert.

    Parameters
    ----------
    alert_id      UUID string of the alert row to investigate.
    auto_approve  Skip the human-review interrupt node (default True).
                  Set False only for interactive CLI usage.

    Returns
    -------
    The final LangGraph state dict, including compliance_memo, verdict,
    confidence, and optionally error.
    """
    load_dotenv()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY is not set. Add it to .env or export it in your shell."
        )

    print("=" * 60)
    print("  investigate_trade")
    print("=" * 60)
    print(f"  alert_id:     {alert_id}")
    print(f"  auto_approve: {auto_approve}")

    graph  = build_graph(auto_approve=auto_approve)
    config = {"configurable": {"thread_id": alert_id}}
    result = graph.invoke({"alert_id": alert_id}, config)

    print("\n" + "─" * 49)
    print(f"  verdict:    {result.get('verdict', 'N/A')}")
    print(f"  confidence: {result.get('confidence', 'N/A')}")
    if result.get("error"):
        print(f"  error:      {result['error']}")
    print("─" * 49)

    return result
