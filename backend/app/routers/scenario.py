from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import SessionLocal, get_db
from ..deps import require_roles
from ..services import scenario

router = APIRouter(prefix="/api/scenario", tags=["scenario"])


@router.post("/l7/compare")
def l7_compare(db: Session = Depends(get_db),
               _: models.User = Depends(require_roles("admin", "safety"))):
    """L-7 整批冻结 vs 单包隔离策略对比（事务回滚，不改变真实数据）。"""
    users = {}
    for role in ("admin", "safety", "dismantler", "warehouse"):
        users[role] = db.scalar(select(models.User).where(models.User.role == role))
    return scenario.run_comparison(lambda: SessionLocal(), users)
