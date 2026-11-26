from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/logs")
def list_logs(limit: int = 200, db: Session = Depends(get_db),
              _: models.User = Depends(get_current_user)):
    rows = db.scalars(
        select(models.AuditLog).order_by(models.AuditLog.id.desc()).limit(limit)
    ).all()
    return [
        {"id": r.id, "actor_id": r.actor_id, "action": r.action,
         "entity": r.entity, "entity_id": r.entity_id, "detail": r.detail,
         "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]
