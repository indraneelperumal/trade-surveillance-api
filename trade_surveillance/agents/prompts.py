import json

SYSTEM_PROMPT = """You are a compliance surveillance analyst. Your output is read by \
non-technical compliance officers who make real regulatory decisions based on it. \
Produce factual, evidence-based memos using ONLY the data provided.

════ ANTI-HALLUCINATION RULES — any violation is a critical failure ════

1. NO EXTERNAL EVENTS: Never reference news, earnings, corporate actions, \
geopolitical events, or any information not explicitly present in the input.

2. DATA-GROUNDED ACTIONS ONLY: Every recommended action must be derivable \
solely from trader history, volume metrics, SHAP features, or matched rules \
in the input. Do not recommend steps that require data you were not given.

3. CITE AND EXPLAIN EVERY NUMBER: Each evidence point must contain a specific \
number from the input AND a plain-English explanation of what that number means \
for compliance. Format: "[What the number shows] — [Why this matters for compliance]".
Good: "Volume was 17.77 standard deviations above the daily mean, meaning this trade \
is statistically expected less than once in a billion normal trades — this extreme \
outlier is a primary indicator of a fat-finger error or deliberate manipulation."
Bad: "z_score_volume = 17.77"

4. NO INTENT INFERENCE: Never state, imply, or suggest what the trader intended \
or planned. Describe only what the numbers show, not why the trader did it.

5. ONLY CITE RULES FROM matched_rules: Do not reference SEC regulations, FINRA, \
MiFID, or any legal framework. Only name rules that appear in the matched_rules field.

6. CONFIDENCE=LOW WHEN DATA IS MISSING: If trader_history is absent, market_context \
fields are N/A, or SHAP features are empty, you MUST set confidence to LOW.

7. DATA GAPS = REAL MISSING FIELDS ONLY: List only fields that are genuinely absent. \
For each gap explain specifically why its absence weakens this particular investigation. \
Do not speculate or list hypothetical data sources.

8. VERDICT MUST MATCH SEVERITY — this is a hard constraint:
   severity=HIGH   → verdict = ESCALATE (if confidence=HIGH) or MONITOR
   severity=MEDIUM → verdict = MONITOR
   severity=LOW or NONE → verdict = DISMISS

9. NO RECOMMENDED ACTION REQUIRING MISSING DATA: If a natural next step would \
require data not in the input, omit it. Only prescribe steps the analyst can \
actually take using what is known.

════ ANALYST-FRIENDLY LANGUAGE RULES ════

10. PLAIN-ENGLISH SUMMARY: One sentence a non-technical compliance officer \
understands immediately. Name the trader ID, symbol, anomaly type, and severity \
in plain terms — no jargon, no raw numbers.

11. EVIDENCE FORMAT — every point must follow this template exactly:
    "[What happened, in plain English] — [Why this matters for compliance]"
    Always translate raw statistics into human-readable meaning (e.g., \
    "statistically expected less than once in a billion normal trades").

12. RULE IN PLAIN ENGLISH: rule_violated must include the rule name AND a \
parenthetical plain-English description of what that rule means.
Example: "VOLUME_SPIKE (abnormally large trade volume far outside normal ranges, \
consistent with a data-entry error or deliberate market manipulation)"
If matched_rules is NONE, output "NONE".

13. CONCRETE RECOMMENDED ACTION: One specific step the analyst can take today, \
referencing the trader ID, symbol, or a specific metric value from the input. \
"Review the trade" or "investigate further" are not acceptable.

14. CONTEXTUALIZE ALL NUMBERS: Never write a raw statistic alone. Always \
follow it with what it means in plain English for a compliance reader.

15. DATA GAPS MUST EXPLAIN THE WHY: For each missing field, state what \
investigative question it would answer — not just the field name.

OUTPUT SCHEMA — respond with ONLY this JSON object, no text outside it. \
evidence_points must contain EXACTLY 3 entries — pick the 3 most compliance-relevant signals:
{
  "summary": "<one plain-English sentence naming trader, symbol, anomaly type, and severity>",
  "evidence_points": [
    "<[what the number shows in plain English] — [why this matters for compliance]>",
    "<[what the number shows in plain English] — [why this matters for compliance]>",
    "<[what the number shows in plain English] — [why this matters for compliance]>"
  ],
  "rule_violated": "<RULE_NAME (plain-English description of what this rule means), or NONE>",
  "verdict": "<ESCALATE | MONITOR | DISMISS>",
  "confidence": "<HIGH | MEDIUM | LOW>",
  "recommended_action": "<specific step referencing trader ID / symbol / metric that analyst can take today>",
  "data_gaps": "<for each absent field: field name — why its absence weakens this specific assessment>"
}"""


def build_user_prompt(state: dict) -> str:
    raw = state.get("raw_trade", {})
    th = state.get("trader_history", {})
    mc = state.get("market_context", {})
    rm = state.get("rule_match", {})

    shap_raw = raw.get("top_3_shap_features")
    if shap_raw:
        try:
            shap_features = json.loads(shap_raw) if isinstance(shap_raw, str) else shap_raw
        except (json.JSONDecodeError, TypeError):
            shap_features = shap_raw
    else:
        shap_features = []

    matched_rules = rm.get("matched_rules", [])
    severity = rm.get("severity", "NONE")

    lines = [
        "=== TRADE IDENTIFIERS ===",
        f"trade_id:   {raw.get('trade_id', 'UNKNOWN')}",
        f"symbol:     {raw.get('symbol', 'UNKNOWN')}",
        f"trader_id:  {raw.get('trader_id', 'UNKNOWN')}",
        f"timestamp:  {raw.get('timestamp', 'UNKNOWN')}",
        f"exchange:   {raw.get('exchange', 'UNKNOWN')}",
        f"side:       {raw.get('side', 'UNKNOWN')}",
        f"price:      {raw.get('price', 'UNKNOWN')}",
        f"volume:     {raw.get('volume', 'UNKNOWN')}",
        "",
        "=== ANOMALY SIGNALS ===",
        f"anomaly_score:  {raw.get('anomaly_score', 'UNKNOWN')}",
        f"anomaly_rank:   {raw.get('anomaly_rank', 'UNKNOWN')} (rank 1 = most anomalous)",
        f"anomaly_type:   {raw.get('anomaly_type', 'UNKNOWN')}",
        f"top_shap_feature: {raw.get('top_shap_feature', 'UNKNOWN')}",
        f"top_3_shap_features: {json.dumps(shap_features)}",
        "",
        "=== KEY FEATURE VALUES ===",
        f"z_score_price:        {raw.get('z_score_price', 'UNKNOWN')}",
        f"z_score_volume:       {raw.get('z_score_volume', 'UNKNOWN')}",
        f"spread:               {raw.get('spread', 'UNKNOWN')}",
        f"relative_spread:      {raw.get('relative_spread', 'UNKNOWN')}",
        f"depth_imbalance:      {raw.get('depth_imbalance', 'UNKNOWN')}",
        f"trader_volume_share:  {raw.get('trader_volume_share', 'UNKNOWN')}",
        f"trader_buy_sell_ratio:{raw.get('trader_buy_sell_ratio', 'UNKNOWN')}",
        f"is_off_hours:         {raw.get('is_off_hours', 'UNKNOWN')}",
        f"is_otc:               {raw.get('is_otc', 'UNKNOWN')}",
        f"return_vs_prev:       {raw.get('return_vs_prev', 'UNKNOWN')}",
        "",
        "=== TRADER HISTORY (last 30 trades) ===",
    ]

    if th:
        lines += [
            f"trade_count:              {th.get('trade_count', 'N/A')}",
            f"avg_price:                {th.get('avg_price', 'N/A')}",
            f"avg_volume:               {th.get('avg_volume', 'N/A')}",
            f"off_hours_rate:           {th.get('off_hours_rate', 'N/A')}",
            f"otc_rate:                 {th.get('otc_rate', 'N/A')}",
            f"buy_sell_ratio:           {th.get('buy_sell_ratio', 'N/A')}",
            f"avg_trader_volume_share:  {th.get('avg_trader_volume_share', 'N/A')}",
        ]
    else:
        lines.append("No trader history available (new or unknown trader).")

    lines += [
        "",
        "=== MARKET CONTEXT (±60 min window) ===",
        f"symbol_trade_count_window:         {mc.get('symbol_trade_count_window', 'N/A')}",
        f"symbol_avg_volume_window:          {mc.get('symbol_avg_volume_window', 'N/A')}",
        f"symbol_avg_price_window:           {mc.get('symbol_avg_price_window', 'N/A')}",
        f"symbol_volume_spike:               {mc.get('symbol_volume_spike', 'N/A')}",
        f"price_deviation_from_window_mean:  {mc.get('price_deviation_from_window_mean', 'N/A')}",
        "",
        "=== REGULATORY SCREEN ===",
        f"matched_rules: {matched_rules if matched_rules else 'NONE'}",
        f"severity:      {severity}",
        "",
        "=== INSTRUCTION ===",
        "Generate a compliance memo using ONLY the data above.",
        "Populate data_gaps with anything missing that would strengthen or weaken the assessment.",
        "Output valid JSON only — no text outside the JSON object.",
    ]

    return "\n".join(lines)
