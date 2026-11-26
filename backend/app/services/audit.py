from sqlalchemy.orm import Session

from .. import models


def log(db: Session, actor_id: int | None, action: str, entity: str, entity_id=None, detail: dict | None = None):
    entry = models.AuditLog(
        actor_id=actor_id,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        detail=detail or {},
    )
    db.add(entry)
    return entry
