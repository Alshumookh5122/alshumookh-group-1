"""
Client-Admin Live Chat API
==========================
Public endpoints for clients + admin-only endpoints for the dashboard.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, update, delete, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import ChatSession, ChatMessage
from app.auth import is_admin_request_authenticated

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


# ─── Pydantic Schemas ─────────────────────────────────────────────────────────

class StartChatRequest(BaseModel):
    client_name: str
    client_email: Optional[str] = None
    client_company: Optional[str] = None
    subject: Optional[str] = None
    message: str


class ContinueChatRequest(BaseModel):
    session_id: str
    client_name: str
    message: str


class AdminReplyRequest(BaseModel):
    message: str


# ─── CLIENT ENDPOINTS (public — no auth) ─────────────────────────────────────

@router.post("/start")
async def start_chat(req: StartChatRequest, db: AsyncSession = Depends(get_db)):
    """Client starts a new support chat session."""
    session = ChatSession(
        client_name=req.client_name.strip(),
        client_email=req.client_email,
        client_company=req.client_company,
        subject=req.subject,
    )
    db.add(session)
    await db.flush()

    msg = ChatMessage(
        session_id=session.id,
        sender="client",
        message=req.message.strip(),
    )
    db.add(msg)

    # Update unread count
    session.unread_count = 1
    await db.commit()
    await db.refresh(session)

    return {
        "session_id": session.id,
        "message_id": msg.id,
        "created_at": session.created_at.isoformat(),
    }


@router.post("/reply")
async def client_reply(req: ContinueChatRequest, db: AsyncSession = Depends(get_db)):
    """Client sends a follow-up message to an existing session."""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == req.session_id,
            ChatSession.is_deleted_by_admin == False,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")

    msg = ChatMessage(
        session_id=session.id,
        sender="client",
        message=req.message.strip(),
    )
    db.add(msg)
    session.unread_count = (session.unread_count or 0) + 1
    session.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return {"message_id": msg.id, "session_id": session.id}


@router.get("/session/{session_id}/messages")
async def get_session_messages_public(session_id: str, db: AsyncSession = Depends(get_db)):
    """Client polls for new messages (admin replies) in their session."""
    result = await db.execute(
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .where(
            ChatSession.id == session_id,
            ChatSession.is_deleted_by_admin == False,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")

    return {
        "session_id": session.id,
        "client_name": session.client_name,
        "subject": session.subject,
        "is_open": session.is_open,
        "messages": [
            {
                "id": m.id,
                "sender": m.sender,
                "message": m.message,
                "created_at": m.created_at.isoformat(),
            }
            for m in session.messages
        ],
    }


# ─── ADMIN ENDPOINTS (require admin session) ─────────────────────────────────

async def _require_admin(request: Request):
    if not await is_admin_request_authenticated(request):
        raise HTTPException(401, "Admin authentication required")


@router.get("/admin/sessions")
async def list_chat_sessions(request: Request, db: AsyncSession = Depends(get_db)):
    """Admin: list all active chat sessions."""
    await _require_admin(request)

    result = await db.execute(
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .where(ChatSession.is_deleted_by_admin == False)
        .order_by(ChatSession.updated_at.desc())
    )
    sessions = result.scalars().all()

    return [
        {
            "id": s.id,
            "client_name": s.client_name,
            "client_email": s.client_email,
            "client_company": s.client_company,
            "subject": s.subject,
            "is_open": s.is_open,
            "unread_count": s.unread_count,
            "message_count": len(s.messages),
            "last_message": s.messages[-1].message[:80] if s.messages else "",
            "last_message_sender": s.messages[-1].sender if s.messages else "",
            "created_at": s.created_at.isoformat(),
            "updated_at": s.updated_at.isoformat(),
        }
        for s in sessions
    ]


@router.get("/admin/sessions/{session_id}")
async def get_chat_session(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Admin: get full chat thread."""
    await _require_admin(request)

    result = await db.execute(
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")

    # Mark all client messages as read
    await db.execute(
        update(ChatMessage)
        .where(
            ChatMessage.session_id == session_id,
            ChatMessage.sender == "client",
            ChatMessage.is_read == False,
        )
        .values(is_read=True)
    )
    await db.execute(
        update(ChatSession)
        .where(ChatSession.id == session_id)
        .values(unread_count=0)
    )
    await db.commit()

    return {
        "id": session.id,
        "client_name": session.client_name,
        "client_email": session.client_email,
        "client_company": session.client_company,
        "subject": session.subject,
        "is_open": session.is_open,
        "created_at": session.created_at.isoformat(),
        "messages": [
            {
                "id": m.id,
                "sender": m.sender,
                "message": m.message,
                "is_read": m.is_read,
                "created_at": m.created_at.isoformat(),
            }
            for m in session.messages
        ],
    }


@router.post("/admin/sessions/{session_id}/reply")
async def admin_reply_to_session(
    session_id: str,
    req: AdminReplyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Admin: send a reply to a client chat."""
    await _require_admin(request)

    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")

    msg = ChatMessage(
        session_id=session_id,
        sender="admin",
        message=req.message.strip(),
        is_read=True,
    )
    db.add(msg)
    session.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return {"message_id": msg.id, "session_id": session_id}


@router.patch("/admin/sessions/{session_id}/close")
async def close_chat_session(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Admin: close/reopen a chat session."""
    await _require_admin(request)

    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")

    session.is_open = not session.is_open
    await db.commit()
    return {"is_open": session.is_open}


@router.delete("/admin/sessions/{session_id}")
async def delete_chat_session(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Admin: soft-delete a chat session."""
    await _require_admin(request)

    await db.execute(
        update(ChatSession)
        .where(ChatSession.id == session_id)
        .values(is_deleted_by_admin=True)
    )
    await db.commit()
    return {"deleted": True, "session_id": session_id}


@router.delete("/admin/sessions")
async def delete_all_chat_sessions(request: Request, db: AsyncSession = Depends(get_db)):
    """Admin: delete ALL chat sessions."""
    await _require_admin(request)

    await db.execute(
        update(ChatSession).values(is_deleted_by_admin=True)
    )
    await db.commit()
    return {"deleted_all": True}


@router.get("/admin/unread-count")
async def get_unread_count(request: Request, db: AsyncSession = Depends(get_db)):
    """Admin: get total unread message count."""
    await _require_admin(request)

    result = await db.execute(
        select(sa_func.sum(ChatSession.unread_count)).where(
            ChatSession.is_deleted_by_admin == False
        )
    )
    total = result.scalar() or 0
    return {"unread_count": int(total)}
