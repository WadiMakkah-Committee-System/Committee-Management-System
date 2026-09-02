"""
الهدف:
راوتات REST لوحدة "إدارة القرارات" — القرارات المستقلة فقط. راجعي رأس
app/services/decision_service.py للتفويض والاجتهادات الموثّقة.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.schemas.decision import (
    DecisionCreate,
    DecisionOpenVoting,
    DecisionOut,
    DecisionUpdate,
    DecisionVoteCast,
)
from app.services import decision_service
from app.services.decision_service import (
    DecisionForbiddenError,
    DecisionInvalidStateError,
    DecisionNotFoundError,
    DecisionValidationError,
)

router = APIRouter(prefix="/decisions", tags=["decisions"])

_SERVICE_ERRORS = (
    DecisionNotFoundError,
    DecisionForbiddenError,
    DecisionInvalidStateError,
    DecisionValidationError,
)


def _handle_errors(exc: Exception) -> Exception:
    if isinstance(exc, DecisionNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, DecisionForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, DecisionInvalidStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, (DecisionValidationError, ValueError)):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    raise exc


@router.post("", response_model=DecisionOut, status_code=status.HTTP_201_CREATED)
async def create_decision(
    payload: DecisionCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> DecisionOut:
    try:
        decision = await decision_service.create_decision(
            db,
            actor=current_user,
            committee_id=payload.committee_id,
            title=payload.title,
            classification=payload.classification,
            start_date=payload.start_date,
            end_date=payload.end_date,
            assignee_ids=payload.assignee_ids,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return DecisionOut.model_validate(decision)


@router.get("", response_model=list[DecisionOut])
async def list_decisions(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[DecisionOut]:
    decisions = await decision_service.list_decisions(db, actor=current_user)
    return [DecisionOut.model_validate(d) for d in decisions]


@router.get("/{decision_id}", response_model=DecisionOut)
async def get_decision(
    decision_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> DecisionOut:
    try:
        decision = await decision_service.get_decision(db, decision_id, actor=current_user)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return DecisionOut.model_validate(decision)


@router.patch("/{decision_id}", response_model=DecisionOut)
async def update_decision(
    decision_id: uuid.UUID,
    payload: DecisionUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DecisionOut:
    try:
        decision = await decision_service.update_decision(
            db,
            actor=current_user,
            decision_id=decision_id,
            title=payload.title,
            classification=payload.classification,
            start_date=payload.start_date,
            end_date=payload.end_date,
            assignee_ids=payload.assignee_ids,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return DecisionOut.model_validate(decision)


@router.delete("/{decision_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_decision(
    decision_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    try:
        await decision_service.delete_decision(db, actor=current_user, decision_id=decision_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc


@router.post("/{decision_id}/open-voting", response_model=DecisionOut)
async def open_voting(
    decision_id: uuid.UUID,
    payload: DecisionOpenVoting,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DecisionOut:
    try:
        decision = await decision_service.open_voting(
            db,
            actor=current_user,
            decision_id=decision_id,
            voting_deadline=payload.voting_deadline,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return DecisionOut.model_validate(decision)


@router.post("/{decision_id}/vote", response_model=DecisionOut)
async def cast_vote(
    decision_id: uuid.UUID,
    payload: DecisionVoteCast,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DecisionOut:
    try:
        decision = await decision_service.cast_vote(
            db, actor=current_user, decision_id=decision_id, choice=payload.choice
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return DecisionOut.model_validate(decision)


@router.post("/{decision_id}/approve", response_model=DecisionOut)
async def approve_decision(
    decision_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> DecisionOut:
    try:
        decision = await decision_service.approve_decision(
            db, actor=current_user, decision_id=decision_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return DecisionOut.model_validate(decision)
