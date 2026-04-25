import json
import os
import warnings

import anthropic
import pandas as pd
from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from typing_extensions import TypedDict

from trade_surveillance.agents.prompts import SYSTEM_PROMPT, build_user_prompt
from trade_surveillance.agents.tools import (
    compute_market_context,
    compute_trader_stats,
    load_anomaly_record,
    load_market_window,
    load_trader_history,
    upload_memo_to_s3,
)


class TradeState(TypedDict, total=False):
    trade_id: str
    raw_trade: dict
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


def _make_trade_context_node(profile: str):
    def trade_context_node(state: TradeState) -> dict:
        try:
            record = load_anomaly_record(state["trade_id"], profile)
            trader_id = record.get("trader_id")
            history_df = load_trader_history(trader_id, profile) if trader_id else pd.DataFrame()
            stats = compute_trader_stats(history_df)

            shap_raw = record.get("top_3_shap_features")
            if shap_raw:
                try:
                    shap_features = json.loads(shap_raw) if isinstance(shap_raw, str) else shap_raw
                except (json.JSONDecodeError, TypeError):
                    shap_features = []
            else:
                shap_features = []

            return {
                "raw_trade": record,
                "trader_history": stats,
                "anomaly_score": float(record.get("anomaly_score", 0)),
                "anomaly_rank": float(record.get("anomaly_rank", 0)),
                "anomaly_type": str(record.get("anomaly_type") or "unknown"),
                "shap_features": shap_features,
            }
        except Exception as exc:
            return {"error": str(exc)}

    return trade_context_node


def _make_market_context_node(profile: str):
    def market_context_node(state: TradeState) -> dict:
        if state.get("error"):
            return {}
        try:
            raw = state.get("raw_trade", {})
            symbol = raw.get("symbol")
            timestamp = raw.get("timestamp")
            if not symbol or timestamp is None:
                return {"market_context": {}}
            window_df = load_market_window(symbol, pd.Timestamp(timestamp), profile)
            context = compute_market_context(window_df, raw)
            return {"market_context": context}
        except Exception as exc:
            return {"error": str(exc)}

    return market_context_node


def _make_regulatory_screen_node():
    def regulatory_screen_node(state: TradeState) -> dict:
        if state.get("error"):
            return {}
        try:
            raw = state.get("raw_trade", {})

            z_price = float(raw.get("z_score_price", 0) or 0)
            z_vol = float(raw.get("z_score_volume", 0) or 0)
            off_hrs = bool(raw.get("is_off_hours", False))
            d_imb = abs(float(raw.get("depth_imbalance", 0) or 0))
            bsr = float(raw.get("trader_buy_sell_ratio", 0) or 0)

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


def human_review_node(state: TradeState) -> dict:
    raw = state.get("raw_trade", {})
    rm = state.get("rule_match", {})
    th = state.get("trader_history", {})
    print("\n" + "=" * 60)
    print("  HIGH SEVERITY TRADE — HUMAN REVIEW REQUIRED")
    print("=" * 60)
    print(f"  trade_id:     {state.get('trade_id')}")
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


def _make_compliance_memo_node(profile: str):
    def compliance_memo_node(state: TradeState) -> dict:
        if state.get("error"):
            memo = {
                "summary": "Investigation failed due to a pipeline error.",
                "evidence_points": [state["error"]],
                "rule_violated": "NONE",
                "verdict": "ERROR",
                "confidence": "LOW",
                "recommended_action": "Investigate pipeline error before re-running.",
                "data_gaps": "Full trade data unavailable due to error.",
            }
            return {"compliance_memo": memo, "verdict": "ERROR", "confidence": "LOW"}

        try:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            client = anthropic.Anthropic(api_key=api_key)
            prompt = build_user_prompt(state)

            response = client.messages.create(
                model="claude-sonnet-4-6",
                temperature=0,
                max_tokens=1800,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = response.content[0].text.strip()

            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
                raw_text = raw_text.strip()

            try:
                memo = json.loads(raw_text)
            except json.JSONDecodeError:
                warnings.warn(f"Claude returned non-JSON: {raw_text[:200]}")
                memo = {
                    "summary": "JSON parse error — raw response stored.",
                    "evidence_points": [raw_text[:500]],
                    "rule_violated": "NONE",
                    "verdict": "MONITOR",
                    "confidence": "LOW",
                    "recommended_action": "Re-run investigation with corrected prompt.",
                    "data_gaps": "Structured response unavailable.",
                }

            severity = state.get("rule_match", {}).get("severity", "NONE")
            confidence = memo.get("confidence", "LOW")

            if severity == "HIGH" and confidence == "HIGH":
                memo["verdict"] = "ESCALATE"
            elif severity == "HIGH":
                memo["verdict"] = "MONITOR"
            elif severity == "MEDIUM":
                memo["verdict"] = "MONITOR"
            elif severity in ("LOW", "NONE"):
                memo["verdict"] = "DISMISS"

            trade_id = state.get("trade_id", "UNKNOWN")
            upload_memo_to_s3(trade_id, memo, profile)

            return {
                "compliance_memo": memo,
                "verdict": memo["verdict"],
                "confidence": memo.get("confidence", "LOW"),
            }
        except Exception as exc:
            warnings.warn(f"compliance_memo_node error: {exc}")
            return {"error": str(exc), "verdict": "ERROR", "confidence": "LOW"}

    return compliance_memo_node


def build_graph(profile: str, auto_approve: bool = False):
    trade_context_node = _make_trade_context_node(profile)
    market_context_node = _make_market_context_node(profile)
    regulatory_screen_node = _make_regulatory_screen_node()
    compliance_memo_node = _make_compliance_memo_node(profile)

    def severity_router(state: TradeState) -> str:
        if state.get("error"):
            return "compliance_memo_node"
        severity = state.get("rule_match", {}).get("severity", "NONE")
        if severity == "HIGH" and not auto_approve:
            return "human_review_node"
        return "compliance_memo_node"

    graph = StateGraph(TradeState)
    graph.add_node("trade_context_node", trade_context_node)
    graph.add_node("market_context_node", market_context_node)
    graph.add_node("regulatory_screen_node", regulatory_screen_node)
    graph.add_node("compliance_memo_node", compliance_memo_node)

    if not auto_approve:
        graph.add_node("human_review_node", human_review_node)
        graph.add_edge("human_review_node", "compliance_memo_node")

    graph.add_edge(START, "trade_context_node")
    graph.add_edge("trade_context_node", "market_context_node")
    graph.add_edge("market_context_node", "regulatory_screen_node")
    graph.add_conditional_edges(
        "regulatory_screen_node",
        severity_router,
        {
            "human_review_node": "human_review_node" if not auto_approve else "compliance_memo_node",
            "compliance_memo_node": "compliance_memo_node",
        },
    )
    graph.add_edge("compliance_memo_node", END)

    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


def investigate_trade(
    trade_id: str,
    profile=None,
    auto_approve: bool = False,
) -> dict:
    load_dotenv()
    if profile is None:
        profile = os.environ.get("AWS_PROFILE", "default")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY is not set. Add it to .env or export it in your shell."
        )

    print("=" * 60)
    print("  investigate_trade")
    print("=" * 60)
    print(f"  trade_id:     {trade_id}")
    print(f"  profile:      {profile}")
    print(f"  auto_approve: {auto_approve}")

    graph = build_graph(profile, auto_approve)
    config = {"configurable": {"thread_id": trade_id}}

    result = graph.invoke({"trade_id": trade_id}, config)

    print("\n" + "─" * 49)
    print(f"  verdict:    {result.get('verdict', 'N/A')}")
    print(f"  confidence: {result.get('confidence', 'N/A')}")
    if result.get("error"):
        print(f"  error:      {result['error']}")
    print("─" * 49)

    return result
