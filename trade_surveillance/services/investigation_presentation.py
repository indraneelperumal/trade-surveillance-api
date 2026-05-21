from __future__ import annotations

from trade_surveillance.domain.enums import (
    REVIEW_AI_COMPLETE,
    VERDICT_DISMISS,
    VERDICT_ESCALATE,
    VERDICT_MONITOR,
)
from trade_surveillance.models.investigation import Investigation
from trade_surveillance.schemas.cases import (
    InvestigationHeadline,
    InvestigationPresentation,
    InvestigationRuleItem,
    InvestigationSection,
)

_VERDICT_UI = {
    VERDICT_ESCALATE: (
        "AI recommends escalation",
        "Not a final regulatory action — human review required.",
    ),
    VERDICT_MONITOR: (
        "AI recommends monitoring",
        "Continue surveillance; no immediate escalation.",
    ),
    VERDICT_DISMISS: (
        "AI suggests dismiss",
        "Suggestion only — not a final disposition. Analyst approval required.",
    ),
}

_CONFIDENCE_LABELS = {"HIGH": "High confidence", "MEDIUM": "Medium confidence", "LOW": "Low confidence"}


def _parse_rules(rule_violated: str | None) -> list[InvestigationRuleItem]:
    if not rule_violated or not rule_violated.strip():
        return []
    items: list[InvestigationRuleItem] = []
    for part in rule_violated.split(";"):
        chunk = part.strip()
        if not chunk:
            continue
        name = chunk.split("(")[0].strip()
        code = name.upper().replace(" ", "_").replace("/", "_")[:48] or "RULE"
        items.append(
            InvestigationRuleItem(
                rule_code=code,
                label=name,
                status="triggered",
                detail=chunk if "(" in chunk else None,
            )
        )
    return items


def build_investigation_presentation(record: Investigation) -> InvestigationPresentation:
    verdict = (record.verdict or VERDICT_MONITOR).upper()
    label, hint = _VERDICT_UI.get(verdict, (verdict.title(), None))
    confidence = (record.confidence or "").upper() or None

    sections: list[InvestigationSection] = []

    if record.summary:
        sections.append(
            InvestigationSection(id="summary", title="Executive summary", body=record.summary)
        )

    rules = _parse_rules(record.rule_violated)
    if rules:
        sections.append(
            InvestigationSection(
                id="rules",
                title="US regulatory screening",
                items=rules,
            )
        )

    evidence = record.evidence_points if isinstance(record.evidence_points, list) else []
    bullets = [str(p) for p in evidence if p]
    if bullets:
        sections.append(
            InvestigationSection(id="evidence", title="Evidence", bullets=bullets)
        )

    if record.recommended_action:
        sections.append(
            InvestigationSection(
                id="recommended_action",
                title="Recommended next steps",
                body=record.recommended_action,
            )
        )

    gaps = (record.data_gaps or "").strip()
    if gaps:
        sections.append(
            InvestigationSection(
                id="data_gaps",
                title="Data gaps & limitations",
                body=gaps,
                emphasis="warning",
            )
        )
    elif verdict == VERDICT_DISMISS:
        sections.append(
            InvestigationSection(
                id="data_gaps",
                title="Data gaps & limitations",
                body="No additional data gaps reported by the agent.",
                emphasis="default",
            )
        )

    review_status = getattr(record, "review_status", None) or REVIEW_AI_COMPLETE

    return InvestigationPresentation(
        id=record.id,
        alert_id=record.alert_id,
        review_status=review_status,
        headline=InvestigationHeadline(
            verdict=verdict,
            verdict_label=label,
            verdict_hint=hint,
            confidence=confidence,
            confidence_label=_CONFIDENCE_LABELS.get(confidence or "", confidence),
            model_version=record.model_version,
            completed_at=record.completed_at,
        ),
        sections=sections,
        error=record.error_message,
    )
