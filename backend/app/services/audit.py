from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AuditLog


def audit(db: Session, action: str, user_id: str | None = None, ip: str | None = None, **detail) -> None:
    db.add(AuditLog(user_id=user_id, action=action, ip=ip, detail=detail))
