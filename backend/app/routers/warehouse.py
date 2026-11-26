from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user, require_roles
from ..schemas import CloseBatchIn, PickIn, RecallIn, ShipIn, SignOffIn, WeighIn
from ..serializers import (
    batch_out,
    notification_out,
    outbound_out,
    picking_out,
    signoff_out,
)
from ..services import warehouse

router = APIRouter(prefix="/api/warehouse", tags=["warehouse"])


@router.get("/picking")
def list_picking(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return [picking_out(db, p) for p in warehouse.list_picking(db)]


@router.post("/pick")
def pick(body: PickIn, db: Session = Depends(get_db),
         user: models.User = Depends(require_roles("warehouse", "admin"))):
    order = warehouse.pick(db, user=user, picking_id=body.picking_id)
    db.commit()
    return {"ok": True, "picking": picking_out(db, order)}


@router.get("/outbound")
def list_outbound(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.scalars(select(models.OutboundOrder).order_by(models.OutboundOrder.id)).all()
    return [outbound_out(db, o) for o in rows]


@router.post("/ship")
def ship(body: ShipIn, db: Session = Depends(get_db),
         user: models.User = Depends(require_roles("warehouse", "admin"))):
    order = warehouse.ship(db, user=user, outbound_id=body.outbound_id)
    db.commit()
    return {"ok": True, "outbound": outbound_out(db, order)}


@router.post("/sign-off")
def sign_off(body: SignOffIn, db: Session = Depends(get_db),
             user: models.User = Depends(require_roles("downstream", "admin"))):
    """下游签收端：签收或拒收；拒收退回隔离待复核，不自动回可用库存。"""
    record = warehouse.sign_off(
        db, user=user, outbound_id=body.outbound_id, action=body.action,
        signer=body.signer, note=body.note,
    )
    db.commit()
    return {"ok": True, "sign_off": signoff_out(record)}


@router.get("/sign-offs")
def list_signoffs(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.scalars(select(models.SignOff)).all()
    return [signoff_out(s) for s in rows]


@router.get("/notifications")
def list_notifications(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.scalars(select(models.BuyerNotification).order_by(models.BuyerNotification.id)).all()
    return [notification_out(n) for n in rows]


@router.post("/recall")
def recall(body: RecallIn, db: Session = Depends(get_db),
           user: models.User = Depends(require_roles("admin", "safety"))):
    """装车后货物不可删除，只能召回/退运。"""
    order = warehouse.recall_or_return(
        db, user=user, outbound_id=body.outbound_id, kind=body.kind, reason=body.reason
    )
    db.commit()
    return {"ok": True, "recall_id": order.id}


@router.post("/recycle-weighing")
def recycle_weighing(body: WeighIn, db: Session = Depends(get_db),
                     user: models.User = Depends(require_roles("warehouse", "admin"))):
    rec = warehouse.weigh_recycle(db, user=user, serial_no=body.serial_no,
                                  weight_kg=body.weight_kg)
    db.commit()
    return {"ok": True, "weighing_id": rec.id, "weight_kg": rec.weight_kg}


@router.get("/reconciliation/{batch_no}")
def reconciliation(batch_no: str, db: Session = Depends(get_db),
                   _: models.User = Depends(get_current_user)):
    batch = db.scalar(select(models.Batch).where(models.Batch.batch_no == batch_no))
    if not batch:
        return {"exists": False}
    stats = warehouse.compute_reconciliation(db, batch)
    return {"exists": True, "batch": batch_out(db, batch), "stats": stats}


@router.post("/close-batch")
def close_batch(body: CloseBatchIn, db: Session = Depends(get_db),
                user: models.User = Depends(require_roles("admin", "safety"))):
    """差额未解释前阻止结清。"""
    batch = warehouse.close_batch(db, user=user, batch_no=body.batch_no,
                                  explanation=body.explanation)
    db.commit()
    return {"ok": True, "batch": batch_out(db, batch)}
