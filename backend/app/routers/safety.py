from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user, require_roles
from ..schemas import ApprovalIn, DeviceIn, InspectionIn, ThermalCloseIn
from ..serializers import approval_out, device_out, inspection_out, pack_out
from ..services import safety
from ..services.errors import NotFoundError

router = APIRouter(prefix="/api/safety", tags=["safety"])


@router.post("/devices")
def add_device(body: DeviceIn, db: Session = Depends(get_db),
               _: models.User = Depends(require_roles("safety", "admin"))):
    dev = safety.add_device(db, device_no=body.device_no, name=body.name,
                            calibrated_until=body.calibrated_until)
    db.commit()
    return {"ok": True, "device": device_out(dev)}


@router.get("/devices")
def list_devices(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return [device_out(d) for d in db.scalars(select(models.Device)).all()]


@router.post("/inspections")
def submit_inspection(body: InspectionIn, db: Session = Depends(get_db),
                      user: models.User = Depends(require_roles("safety", "admin"))):
    """检测台回执。"""
    rec = safety.submit_inspection(
        db, user=user, serial_no=body.serial_no, device_no=body.device_no,
        insulation_pass=body.insulation_pass, bms_reading_ok=body.bms_reading_ok,
        is_reinspection=body.is_reinspection, note=body.note,
    )
    db.commit()
    return {"ok": True, "inspection": inspection_out(db, rec)}


@router.get("/inspections")
def list_inspections(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.scalars(select(models.InspectionRecord).order_by(models.InspectionRecord.id)).all()
    return [inspection_out(db, r) for r in rows]


@router.post("/thermal/close")
def close_thermal(body: ThermalCloseIn, db: Session = Depends(get_db),
                  user: models.User = Depends(require_roles("safety", "admin"))):
    ev = db.get(models.TransportEvent, body.event_id)
    if not ev or ev.event_type != "thermal":
        raise NotFoundError("热事件不存在")
    ev.case_closed = body.closed
    db.commit()
    return {"ok": True}


@router.get("/echelon-blockers/{serial_no}")
def echelon_blockers(serial_no: str, db: Session = Depends(get_db),
                     _: models.User = Depends(get_current_user)):
    pack = db.scalar(select(models.Pack).where(models.Pack.serial_no == serial_no))
    if not pack:
        raise NotFoundError(f"包 {serial_no} 不存在")
    blockers = safety.echelon_blockers(db, pack)
    return {"serial_no": serial_no, "blocked": bool(blockers), "blockers": blockers,
            "pack": pack_out(db, pack)}


@router.post("/approvals")
def approve(body: ApprovalIn, db: Session = Depends(get_db),
            user: models.User = Depends(require_roles("safety", "admin"))):
    """安全工程师审批：echelon / recycle / reinspect（退回补检使旧放行单失效）。"""
    approval = safety.approve(
        db, user=user, serial_no=body.serial_no, decision=body.decision,
        purpose=body.purpose, consignee=body.consignee,
        quantity_limit=body.quantity_limit, rationale=body.rationale,
    )
    db.commit()
    return {"ok": True, "approval": approval_out(db, approval)}


@router.get("/approvals")
def list_approvals(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.scalars(select(models.Approval).order_by(models.Approval.id)).all()
    return [approval_out(db, a) for a in rows]
