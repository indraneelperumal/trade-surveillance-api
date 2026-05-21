from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from trade_surveillance.crud import alerts as alerts_crud
from trade_surveillance.crud import investigation_notes as notes_crud
from trade_surveillance.crud import investigations as investigations_crud
from trade_surveillance.domain.enums import (
    ALERT_CLOSED,
    ALERT_IN_PROGRESS,
    ALERT_OPEN,
    ALERT_PENDING_OFFICER_REVIEW,
    APPROVED_REVIEW_STATUSES,
    DISPOSITION_ESCALATED_REGULATOR,
    DISPOSITION_FALSE_POSITIVE,
    REVIEW_AI_COMPLETE,
    REVIEW_ANALYST_APPROVED,
    REVIEW_OFFICER_APPROVED,
    ROLE_COMPLIANCE_LEAD,
    VALID_DISPOSITIONS,
)
from trade_surveillance.models.alert import Alert
from trade_surveillance.models.user import User
from trade_surveillance.schemas.alerts import AlertRead
from trade_surveillance.schemas.investigation_notes import InvestigationNoteCreate


def _system_note(db: Session, alert_id: UUID, content: str, author_id: UUID | None) -> None:
    notes_crud.create_investigation_note(
        db,
        InvestigationNoteCreate(
            alert_id=alert_id,
            note_type="SYSTEM",
            content=content,
            is_system=True,
        ),
        author_id=author_id,
    )


def assign_alert(
    db: Session,
    alert: Alert,
    *,
    assigned_to: UUID,
    actor: User,
) -> AlertRead:
    if actor.role != ROLE_COMPLIANCE_LEAD and assigned_to != actor.id:
        raise PermissionError("Only compliance officers may assign cases to other users.")
    target = db.get(User, assigned_to)
    if not target or not target.is_active:
        raise ValueError("Assignee user not found or inactive.")

    alert.assigned_to = assigned_to
    if (alert.status or "").upper() == ALERT_OPEN:
        alert.status = ALERT_IN_PROGRESS
    db.add(alert)
    db.commit()
    db.refresh(alert)

    _system_note(
        db,
        alert.id,
        f"Case assigned to {target.email} by {actor.email}.",
        actor.id,
    )
    read = alerts_crud.get_alert_read(db, alert.id)
    assert read is not None
    return read


def take_alert(db: Session, alert: Alert, actor: User) -> AlertRead:
    alert.assigned_to = actor.id
    if (alert.status or "").upper() == ALERT_OPEN:
        alert.status = ALERT_IN_PROGRESS
    db.add(alert)
    db.commit()
    db.refresh(alert)
    _system_note(db, alert.id, f"Case taken by {actor.email}.", actor.id)
    read = alerts_crud.get_alert_read(db, alert.id)
    assert read is not None
    return read


def escalate_alert(db: Session, alert: Alert, actor: User, note: str) -> AlertRead:
    invs = investigations_crud.list_investigations(db, offset=0, limit=1, alert_id=alert.id)
    if not invs:
        raise ValueError("Run and approve an AI investigation before escalating to an officer.")
    inv = invs[0]
    status = getattr(inv, "review_status", REVIEW_AI_COMPLETE)
    if status not in APPROVED_REVIEW_STATUSES:
        raise ValueError("Approve AI investigation findings before escalating.")

    alert.status = ALERT_PENDING_OFFICER_REVIEW
    db.add(alert)
    db.commit()
    db.refresh(alert)

    notes_crud.create_investigation_note(
        db,
        InvestigationNoteCreate(alert_id=alert.id, note_type="HUMAN", content=note),
        author_id=actor.id,
    )
    _system_note(
        db,
        alert.id,
        f"Escalated to compliance officer by {actor.email}.",
        actor.id,
    )
    read = alerts_crud.get_alert_read(db, alert.id)
    assert read is not None
    return read


def close_alert(
    db: Session,
    alert: Alert,
    officer: User,
    *,
    disposition: str,
    note: str,
) -> AlertRead:
    if officer.role != ROLE_COMPLIANCE_LEAD:
        raise PermissionError("Only compliance officers may close alerts.")
    disp = disposition.strip().upper()
    if disp not in VALID_DISPOSITIONS:
        raise ValueError(f"Invalid disposition. Use one of: {', '.join(sorted(VALID_DISPOSITIONS))}.")

    alert.status = ALERT_CLOSED
    alert.disposition = disp
    alert.reviewed_by = officer.id
    alert.reviewed_at = datetime.now(timezone.utc)
    db.add(alert)
    db.commit()
    db.refresh(alert)

    notes_crud.create_investigation_note(
        db,
        InvestigationNoteCreate(alert_id=alert.id, note_type="HUMAN", content=note),
        author_id=officer.id,
    )
    _system_note(
        db,
        alert.id,
        f"Case closed with disposition {disp} by {officer.email}.",
        officer.id,
    )
    read = alerts_crud.get_alert_read(db, alert.id)
    assert read is not None
    return read


def approve_investigation(
    db: Session,
    investigation_id: UUID,
    actor: User,
    *,
    override_note: str | None = None,
) -> None:
    inv = investigations_crud.get_investigation(db, investigation_id)
    if not inv:
        raise ValueError("Investigation not found.")
    if getattr(inv, "review_status", None) != REVIEW_AI_COMPLETE:
        raise ValueError("Investigation is not awaiting approval.")

    inv.review_status = (
        REVIEW_OFFICER_APPROVED
        if actor.role == ROLE_COMPLIANCE_LEAD
        else REVIEW_ANALYST_APPROVED
    )
    db.add(inv)
    db.commit()

    if override_note:
        notes_crud.create_investigation_note(
            db,
            InvestigationNoteCreate(
                alert_id=inv.alert_id,
                investigation_id=inv.id,
                note_type="HUMAN",
                content=override_note,
            ),
            author_id=actor.id,
        )
    _system_note(
        db,
        inv.alert_id,
        f"AI investigation approved by {actor.email}.",
        actor.id,
    )
