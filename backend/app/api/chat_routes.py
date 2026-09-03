"""
backend/app/api/chat_routes.py
================================
AI Chat Assistant API endpoints.

POST /api/chat          — Send a message, get AI response
GET  /api/chat/history  — Get conversation history for a session
DELETE /api/chat/history — Clear conversation history
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatMessageOut(BaseModel):
    id: str
    role: str
    content: str
    source: Optional[str] = None
    created_at: str
    error: bool = False


class ChatResponse(BaseModel):
    message: ChatMessageOut
    session_id: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/chat", response_model=ChatResponse, tags=["AI Chat"])
async def chat(req: ChatRequest) -> ChatResponse:
    """
    Send a message to the AI chat assistant.

    The assistant can answer:
    - Data questions: "How many transactions were blocked today?"
    - System questions: "How does XGBoost work?", "What is SHAP?"

    Uses PandasAI → Ollama → Direct SQL → Rule-based fallback chain.
    Never fails — always returns a useful response.
    """
    import asyncio

    session_id = req.session_id or str(uuid.uuid4())
    message = req.message.strip()

    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    if len(message) > 2000:
        raise HTTPException(status_code=400, detail="Message too long (max 2000 characters)")

    try:
        from app.services.chat_service import get_chat_service
        chat_svc = get_chat_service()

        # Run in thread executor to avoid blocking async event loop
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: chat_svc.chat(message, session_id)
        )

        msg = ChatMessageOut(
            id=str(uuid.uuid4()),
            role="assistant",
            content=result["content"],
            source=result["source"],
            created_at=datetime.now(timezone.utc).isoformat(),
            error=False,
        )

        return ChatResponse(message=msg, session_id=result["session_id"])

    except Exception as e:
        logger.error("Chat endpoint error: %s", e, exc_info=True)
        # Return a friendly error response instead of HTTP 500
        msg = ChatMessageOut(
            id=str(uuid.uuid4()),
            role="assistant",
            content=(
                "I'm having trouble processing your request right now. "
                "This might be because the database is offline or a service error occurred.\n\n"
                "**I can still answer system questions** like:\n"
                "- \"How does XGBoost work?\"\n"
                "- \"What is the Digital Twin?\"\n"
                "- \"Explain SHAP values\"\n\n"
                "For data queries, make sure the backend and database are running."
            ),
            source="rule_based",
            created_at=datetime.now(timezone.utc).isoformat(),
            error=True,
        )
        return ChatResponse(message=msg, session_id=session_id)


@router.get("/chat/history", response_model=List[ChatMessageOut], tags=["AI Chat"])
async def get_chat_history(session_id: str) -> List[ChatMessageOut]:
    """Get conversation history for a session."""
    try:
        from app.services.chat_service import get_chat_service
        chat_svc = get_chat_service()
        history = chat_svc.get_history(session_id)

        return [
            ChatMessageOut(
                id=str(uuid.uuid4()),
                role=msg["role"],
                content=msg["content"],
                source=None,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            for msg in history
        ]
    except Exception as e:
        logger.error("Get history error: %s", e)
        return []


@router.delete("/chat/history", tags=["AI Chat"])
async def clear_chat_history(session_id: str) -> dict:
    """Clear conversation history for a session."""
    try:
        from app.services.chat_service import get_chat_service
        chat_svc = get_chat_service()
        chat_svc.clear_history(session_id)
        return {"cleared": True, "session_id": session_id}
    except Exception as e:
        logger.error("Clear history error: %s", e)
        return {"cleared": False, "error": str(e)}
