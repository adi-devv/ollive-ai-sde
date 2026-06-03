"""
/messages endpoints

POST /messages — save a single chat message (user or assistant turn)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Conversation, Message
from ..schemas import MessageCreate, MessageRead

router = APIRouter(prefix="/messages", tags=["messages"])


def _ensure_conversation(
    db: Session,
    conversation_id: str,
    session_id: str | None,
) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        conv = Conversation(
            id=conversation_id,
            session_id=session_id or "default",
        )
        db.add(conv)
        db.flush()
    else:
        conv.updated_at = datetime.now(timezone.utc)
    return conv


@router.post("", response_model=MessageRead, status_code=201)
def create_message(
    payload: MessageCreate,
    db: Session = Depends(get_db),
) -> Message:
    """
    Store a single chat message.

    The conversation is auto-created if it does not exist yet, matching the
    same behaviour as POST /logs.  Call this for every user and assistant turn
    so that GET /conversations/{id} can replay the full message history.
    """
    _ensure_conversation(db, payload.conversation_id, payload.session_id)

    msg = Message(
        id=str(uuid.uuid4()),
        conversation_id=payload.conversation_id,
        role=payload.role,
        content=payload.content,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg  # type: ignore[return-value]
