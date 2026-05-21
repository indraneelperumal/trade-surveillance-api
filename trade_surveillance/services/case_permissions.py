from __future__ import annotations

from trade_surveillance.domain.enums import (
    ALERT_CLOSED,
    ALERT_PENDING_OFFICER_REVIEW,
    APPROVED_REVIEW_STATUSES,
    REVIEW_AI_COMPLETE,
    ROLE_COMPLIANCE_LEAD,
)
from trade_surveillance.models.alert import Alert
from trade_surveillance.models.investigation import Investigation
from trade_surveillance.models.user import User
from trade_surveillance.schemas.cases import CasePermissions

_INVESTIGABLE = frozenset({"HIGH", "MEDIUM"})


def build_case_permissions(
    current_user: User,
    alert: Alert,
    investigation: Investigation | None,
) -> CasePermissions:
    is_officer = current_user.role == ROLE_COMPLIANCE_LEAD
    status = (alert.status or "").upper()
    severity = (alert.severity or "").upper()
    closed = status == ALERT_CLOSED

    review_status = (
        getattr(investigation, "review_status", None) if investigation else None
    )
    inv_approved = review_status in APPROVED_REVIEW_STATUSES if review_status else False
    inv_ai_complete = review_status == REVIEW_AI_COMPLETE if review_status else False

    can_run_ai = (
        not closed
        and severity in _INVESTIGABLE
        and investigation is None
        and status != ALERT_PENDING_OFFICER_REVIEW
    )

    can_approve = bool(investigation and inv_ai_complete and not closed)

    can_escalate = (
        not closed
        and investigation is not None
        and inv_approved
        and status not in (ALERT_PENDING_OFFICER_REVIEW, ALERT_CLOSED)
    )

    assigned = alert.assigned_to
    is_assignee = assigned == current_user.id if assigned else False

    return CasePermissions(
        can_assign=is_officer and not closed,
        can_take=not closed and (assigned is None or is_assignee or is_officer),
        can_close=is_officer and not closed,
        can_escalate=can_escalate,
        can_run_ai=can_run_ai,
        can_approve_investigation=can_approve,
    )
