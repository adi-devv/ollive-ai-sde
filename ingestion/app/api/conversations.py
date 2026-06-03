"""
/conversations endpoints

GET    /conversations          — list all conversations
GET    /conversations/{id}     — get conversation detail with messages + logs
DELETE /conversations/{id}     — delete a conversation and all its data
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import Conversation
from ..schemas import (
    ConversationDetail,
    ConversationListResponse,
    ConversationRead,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> ConversationListResponse:
    """
    List conversations, newest first.
    Optionally filter by **session_id**.
    """
    stmt = select(Conversation)
    count_stmt = select(func.count()).select_from(Conversation)

    if session_id:
        stmt = stmt.where(Conversation.session_id == session_id)
        count_stmt = count_stmt.where(Conversation.session_id == session_id)

    total: int = db.execute(count_stmt).scalar_one()

    offset = (page - 1) * page_size
    stmt = (
        stmt.order_by(Conversation.updated_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = list(db.scalars(stmt))

    return ConversationListResponse(
        items=items,  # type: ignore[arg-type]
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
) -> Conversation:
    """
    Retrieve a conversation with its full message history and inference logs.
    Returns **404** if not found.
    """
    stmt = (
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(
            selectinload(Conversation.messages),
            selectinload(Conversation.inference_logs),
        )
    )
    conv = db.scalars(stmt).first()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Sort messages and logs by created_at for consistent ordering
    conv.messages.sort(key=lambda m: m.created_at)
    conv.inference_logs.sort(key=lambda l: l.created_at)

    return conv  # type: ignore[return-value]


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
) -> None:
    """
    Delete a conversation and all associated messages and logs.
    Returns **404** if not found, **204 No Content** on success.
    """
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    db.delete(conv)
    db.commit()
