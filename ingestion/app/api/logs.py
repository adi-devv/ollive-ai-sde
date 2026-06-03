"""
/logs endpoints

POST /logs  — ingest a new inference log (+ upsert Conversation)
GET  /logs  — list logs with pagination and optional filters
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Conversation, InferenceLog
from ..schemas import (
    InferenceLogCreate,
    InferenceLogListResponse,
    InferenceLogRead,
)

router = APIRouter(prefix="/logs", tags=["logs"])


def _ensure_conversation(
    db: Session,
    conversation_id: str,
    session_id: str,
) -> Conversation:
    """Return existing conversation or create a new one."""
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        conv = Conversation(
            id=conversation_id,
            session_id=session_id,
        )
        db.add(conv)
        db.flush()  # assign defaults without committing
    else:
        # Touch updated_at
        conv.updated_at = datetime.now(timezone.utc)
    return conv


@router.post("", response_model=InferenceLogRead, status_code=201)
def create_log(
    payload: InferenceLogCreate,
    db: Session = Depends(get_db),
) -> InferenceLog:
    """
    Ingest a new inference log entry.

    The conversation is automatically created if it does not exist yet,
    so the SDK only needs to supply a conversation_id without a separate
    "create conversation" round-trip.
    """
    _ensure_conversation(db, payload.conversation_id, payload.session_id)

    log = InferenceLog(
        id=str(uuid.uuid4()),
        conversation_id=payload.conversation_id,
        message_id=payload.message_id,
        model=payload.model,
        provider=payload.provider,
        latency_ms=payload.latency_ms,
        prompt_tokens=payload.prompt_tokens,
        completion_tokens=payload.completion_tokens,
        total_tokens=payload.total_tokens,
        request_status=payload.request_status,
        error_message=payload.error_message,
        input_preview=payload.input_preview,
        output_preview=payload.output_preview,
        created_at=payload.timestamp or datetime.now(timezone.utc),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log  # type: ignore[return-value]


@router.get("", response_model=InferenceLogListResponse)
def list_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    conversation_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> InferenceLogListResponse:
    """
    List inference logs with optional filters and pagination.

    Filters:
    - **provider** — exact match on provider field (e.g. ``anthropic``)
    - **model** — exact match on model field
    - **status** — ``success`` or ``error``
    - **conversation_id** — restrict to one conversation
    """
    stmt = select(InferenceLog)
    count_stmt = select(func.count()).select_from(InferenceLog)

    if provider:
        stmt = stmt.where(InferenceLog.provider == provider.lower())
        count_stmt = count_stmt.where(InferenceLog.provider == provider.lower())
    if model:
        stmt = stmt.where(InferenceLog.model == model)
        count_stmt = count_stmt.where(InferenceLog.model == model)
    if status:
        stmt = stmt.where(InferenceLog.request_status == status)
        count_stmt = count_stmt.where(InferenceLog.request_status == status)
    if conversation_id:
        stmt = stmt.where(InferenceLog.conversation_id == conversation_id)
        count_stmt = count_stmt.where(
            InferenceLog.conversation_id == conversation_id
        )

    total: int = db.execute(count_stmt).scalar_one()

    offset = (page - 1) * page_size
    stmt = (
        stmt.order_by(InferenceLog.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = list(db.scalars(stmt))

    return InferenceLogListResponse(
        items=items,  # type: ignore[arg-type]
        total=total,
        page=page,
        page_size=page_size,
    )
