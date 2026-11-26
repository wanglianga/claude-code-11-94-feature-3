from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user, require_roles
from ..schemas import (
    LinkModuleIn,
    RelabelIn,
    ResolveUnknownIn,
    UnknownModuleIn,
    WorkOrderIn,
)
from ..serializers import label_out, module_out, work_order_out
from ..services import dismantling
from ..services.errors import BusinessRuleError, NotFoundError

router = APIRouter(prefix="/api/dismantling", tags=["dismantling"])


def _get_user(db: Session, username: str) -> models.User:
    u = db.scalar(select(models.User).where(models.User.username == username))
    if not u:
        raise NotFoundError(f"操作者 {username} 不存在")
    return u


@router.post("/work-orders")
def create_work_order(body: WorkOrderIn, db: Session = Depends(get_db),
                      user: models.User = Depends(require_roles("dismantler", "admin"))):
    order = dismantling.create_work_order(db, user=user, serial_no=body.serial_no, note=body.note)
    db.commit()
    return {"ok": True, "work_order": work_order_out(db, order)}


@router.get("/work-orders")
def list_work_orders(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.scalars(select(models.WorkOrder).order_by(models.WorkOrder.id)).all()
    return [work_order_out(db, w) for w in rows]


@router.post("/link-module")
def link_module(body: LinkModuleIn, db: Session = Depends(get_db),
                user: models.User = Depends(require_roles("dismantler", "admin"))):
    """双方见证扫码建立包→模组关系，两名见证者必须不同。"""
    w1 = _get_user(db, body.witness1)
    w2 = _get_user(db, body.witness2)
    module = dismantling.link_module(
        db, user=user, work_order_id=body.work_order_id,
        module_serial=body.module_serial, witness1=w1, witness2=w2,
    )
    db.commit()
    return {"ok": True, "module": module_out(module)}


@router.post("/unknown-module")
def unknown_module(body: UnknownModuleIn, db: Session = Depends(get_db),
                   user: models.User = Depends(require_roles("dismantler", "safety", "admin"))):
    """无法确认父子关系的模组：隔离待核，禁止自动归到最相似序列号。"""
    module = dismantling.register_unknown_module(
        db, user=user, work_order_id=body.work_order_id,
        module_serial=body.module_serial, reason=body.reason,
    )
    db.commit()
    return {"ok": True, "module": module_out(module)}


@router.post("/resolve-unknown")
def resolve_unknown(body: ResolveUnknownIn, db: Session = Depends(get_db),
                    user: models.User = Depends(require_roles("safety", "admin"))):
    module = dismantling.resolve_unknown_module(
        db, user=user, module_serial=body.module_serial, parent_serial=body.parent_serial
    )
    db.commit()
    return {"ok": True, "module": module_out(module)}


@router.post("/relabel")
def relabel(body: RelabelIn, db: Session = Depends(get_db),
            user: models.User = Depends(require_roles("dismantler", "safety", "admin"))):
    """换标：第一人发起，第二人确认；旧号、操作者、时间全程保留。"""
    op2 = _get_user(db, body.operator2) if body.operator2 else None
    history = dismantling.relabel(
        db, user=user, entity_type=body.entity_type, old_serial=body.old_serial,
        new_serial=body.new_serial, operator1=user, operator2=op2, confirm=body.confirm,
    )
    db.commit()
    return {"ok": True, "confirmed": history.confirmed, "label_history": label_out(history)}


@router.get("/label-history")
def label_history(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.scalars(select(models.LabelHistory).order_by(models.LabelHistory.id)).all()
    return [label_out(h) for h in rows]


@router.get("/modules")
def list_modules(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.scalars(select(models.Module).order_by(models.Module.id)).all()
    return [module_out(m) for m in rows]


@router.post("/work-orders/{work_order_id}/complete")
def complete_work_order(work_order_id: int, db: Session = Depends(get_db),
                        user: models.User = Depends(require_roles("dismantler", "admin"))):
    order = dismantling.complete_work_order(db, user=user, work_order_id=work_order_id)
    db.commit()
    return {"ok": True, "work_order": work_order_out(db, order)}
