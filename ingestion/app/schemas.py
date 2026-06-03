"""
Pydantic schemas for request/response validation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# InferenceLog schemas
# ---------------------------------------------------------------------------


class InferenceLogCreate(BaseModel):
    """Payload accepted by POST /logs."""

    conversation_id: str = Field(..., min_length=1, max_length=36)
    session_id: str = Field(..., min_length=1, max_length=255)
    model: str = Field(..., min_length=1, max_length=128)
    provider: str = Field(..., min_length=1, max_length=64)
    latency_ms: int = Field(default=0, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    request_status: str = Field(default="success", max_length=20)
    error_message: Optional[str] = None
    input_preview: str = Field(default="", max_length=255)
    output_preview: str = Field(default="", max_length=255)
    # Optional: caller may supply a pre-existing message_id
    message_id: Optional[str] = Field(default=None, max_length=36)
    timestamp: Optional[datetime] = None

    @field_validator("request_status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {"success", "error"}
        if v not in allowed:
            raise ValueError(f"request_status must be one of {allowed}")
        return v

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        return v.lower().strip()

    model_config = {"from_attributes": True}


class InferenceLogRead(BaseModel):
    """Schema returned by GET /logs."""

    id: str
    conversation_id: str
    message_id: Optional[str]
    model: str
    provider: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    request_status: str
    error_message: Optional[str]
    input_preview: str
    output_preview: str
    created_at: datetime

    model_config = {"from_attributes": True}


class InferenceLogListResponse(BaseModel):
    items: list[InferenceLogRead]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Message schemas
# ---------------------------------------------------------------------------


class MessageCreate(BaseModel):
    """Payload accepted by POST /messages."""

    conversation_id: str = Field(..., min_length=1, max_length=36)
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)
    session_id: Optional[str] = Field(default=None, max_length=255)

    model_config = {"from_attributes": True}


class MessageRead(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Conversation schemas
# ---------------------------------------------------------------------------


class ConversationRead(BaseModel):
    id: str
    session_id: str
    title: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetail(ConversationRead):
    """Full conversation including messages and logs."""

    messages: list[MessageRead] = []
    inference_logs: list[InferenceLogRead] = []

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    items: list[ConversationRead]
    total: int
    page: int
    page_size: int
