"""Conversations: CRUD, the streaming ask endpoint, and Markdown export."""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.datasets import get_owned_datasets
from app.config import get_settings
from app.db import SessionLocal, get_db
from app.deps import authed_user
from app.logging_setup import log_event
from app.models import Conversation, Dataset, Message, User, utcnow
from app.schemas import AskIn, ConversationCreate, ConversationDetail, ConversationOut, ConversationUpdate
from app.security import rate_limit
from app.services.agent import Agent, TurnResult
from app.services.export import conversation_markdown
from app.services.llm.factory import get_llm

router = APIRouter(prefix="/api/conversations", tags=["conversations"])
log = logging.getLogger(__name__)


def _owned(db: Session, user: User, conversation_id: str) -> Conversation:
    conv = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.owner_id == user.id))
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conv


def _live_datasets(db: Session, user: User, ids: list[str]) -> list[Dataset]:
    """Datasets still present; silently drops ones the user deleted since."""
    if not ids:
        return []
    return list(db.scalars(select(Dataset).where(Dataset.id.in_(ids), Dataset.owner_id == user.id)))


@router.get("", response_model=list[ConversationOut])
def list_conversations(user: User = Depends(authed_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(Conversation).where(Conversation.owner_id == user.id)
                           .order_by(Conversation.updated_at.desc()).limit(100)))


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(body: ConversationCreate, user: User = Depends(authed_user), db: Session = Depends(get_db)):
    get_owned_datasets(db, user, body.dataset_ids)
    conv = Conversation(owner_id=user.id, title=body.title or "New analysis", dataset_ids=body.dataset_ids)
    db.add(conv)
    db.flush()
    return conv


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str, user: User = Depends(authed_user), db: Session = Depends(get_db)):
    return _owned(db, user, conversation_id)


@router.patch("/{conversation_id}", response_model=ConversationOut)
def update_conversation(conversation_id: str, body: ConversationUpdate, user: User = Depends(authed_user),
                        db: Session = Depends(get_db)):
    conv = _owned(db, user, conversation_id)
    if body.dataset_ids is not None:
        get_owned_datasets(db, user, body.dataset_ids)
        conv.dataset_ids = body.dataset_ids
    if body.title is not None:
        conv.title = body.title.strip()
    return conv


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: str, user: User = Depends(authed_user), db: Session = Depends(get_db)):
    db.delete(_owned(db, user, conversation_id))


@router.get("/{conversation_id}/export.md", response_class=PlainTextResponse)
def export_conversation(conversation_id: str, user: User = Depends(authed_user), db: Session = Depends(get_db)):
    conv = _owned(db, user, conversation_id)
    md = conversation_markdown(conv, _live_datasets(db, user, conv.dataset_ids))
    return PlainTextResponse(md, media_type="text/markdown",
                             headers={"Content-Disposition": 'attachment; filename="quarry-report.md"'})


def _sse(event: dict) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"


@router.post("/{conversation_id}/ask")
def ask(conversation_id: str, body: AskIn, user: User = Depends(authed_user), db: Session = Depends(get_db)):
    """Run one analysis turn and stream progress as Server-Sent Events."""
    rate_limit.hit(f"chat:{user.id}", get_settings().chat_rate_limit_per_minute)
    conv = _owned(db, user, conversation_id)
    datasets = _live_datasets(db, user, conv.dataset_ids)
    if not datasets:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Select at least one dataset for this analysis.")

    history = list(conv.messages)
    db.add(Message(conversation_id=conv.id, role="user", content=body.question, artifacts={}))
    if not history and conv.title == "New analysis":
        conv.title = body.question[:80] + ("..." if len(body.question) > 80 else "")
    db.commit()  # persist the question now; the stream below runs after this handler returns
    for obj in (*datasets, *history):
        db.expunge(obj)

    agent = Agent(get_llm(), datasets, user.id)
    user_id, conv_id = user.id, conv.id

    def stream() -> Iterator[str]:
        result = TurnResult()
        failed = False
        yield ": stream-open\n\n"  # flushes proxies and lets the client know we are alive
        try:
            for event in agent.run(body.question, history, result):
                failed = failed or event["type"] == "error"
                yield _sse(event)
        except HTTPException as exc:  # e.g. daily quota hit mid-turn
            failed = True
            yield _sse({"type": "error", "message": exc.detail})
        except Exception:
            failed = True
            log.exception("agent crashed")
            yield _sse({"type": "error", "message": "Something went wrong while analysing. Please try again."})

        with SessionLocal() as s:
            content = result.answer or ("The analysis failed. Please try again." if failed else "")
            msg = Message(conversation_id=conv_id, role="assistant", content=content,
                          artifacts=result.artifacts | {"usage": result.usage, "failed": failed})
            s.add(msg)
            c = s.get(Conversation, conv_id)
            if c is not None:
                c.updated_at = utcnow()
            s.commit()
            log_event(log, "turn_complete", conversation_id=conv_id, user_id=user_id, failed=failed, **result.usage)
            yield _sse({"type": "done", "message_id": msg.id})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
