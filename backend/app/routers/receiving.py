from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user, require_roles
from ..schemas import (
    FreezeBatchIn,
    QuarantinePackIn,
    ReceiveIn,
    ReleaseQuarantineIn,
    UnfreezeBatchIn,
)
from ..serializers import batch_out, pack_out, quarantine_out, receipt_out
from ..services import receiving

router = APIRouter(prefix="/api/receiving", tags=["receiving"])


@router.post("/scan")
def scan_pack(body: ReceiveIn, db: Session = Depends(get_db),
              user: models.User = Depends(require_roles("receiver", "admin"))):
    """模拟扫码器收货：重复扫码只返回原收货单。"""
    pack, receipt, duplicated = receiving.receive_pack(
        db,
        user=user,
        batch_no=body.batch_no,
        serial_no=body.serial_no,
        oem=body.oem,
        source_vehicle=body.source_vehicle,
        scan_payload=body.scan_payload,
        quarantine_slot=body.quarantine_slot,
        responsible_team=body.responsible_team,
        events=[e.model_dump() for e in body.events],
        notes=body.notes,
    )
    db.commit()
    return {"duplicated": duplicated,
            "message": "该序列号已收货，返回原收货单" if duplicated else "收货成功",
            "receipt": receipt_out(db, receipt)}


@router.get("/receipt/{serial_no}")
def get_receipt(serial_no: str, db: Session = Depends(get_db),
                _: models.User = Depends(get_current_user)):
    receipt = receiving.find_receipt_by_serial(db, serial_no)
    if not receipt:
        return {"exists": False, "receipt": None}
    return {"exists": True, "receipt": receipt_out(db, receipt)}


@router.get("/packs")
def list_packs(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    packs = db.scalars(select(models.Pack).order_by(models.Pack.id)).all()
    return [pack_out(db, p) for p in packs]


@router.get("/batches")
def list_batches(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return [batch_out(db, b) for b in db.scalars(select(models.Batch).order_by(models.Batch.id)).all()]


@router.get("/batch/{batch_no}")
def get_batch(batch_no: str, db: Session = Depends(get_db),
              _: models.User = Depends(get_current_user)):
    b = db.scalar(select(models.Batch).where(models.Batch.batch_no == batch_no))
    if not b:
        return {"exists": False}
    return {"exists": True, "batch": batch_out(db, b),
            "packs": [pack_out(db, p) for p in b.packs]}


@router.post("/quarantine/batch")
def freeze_batch(body: FreezeBatchIn, db: Session = Depends(get_db),
                 user: models.User = Depends(require_roles("admin", "safety"))):
    batch = receiving.freeze_batch(db, user=user, batch_no=body.batch_no, reason=body.reason)
    db.commit()
    return {"ok": True, "batch": batch_out(db, batch)}


@router.post("/quarantine/pack")
def quarantine_pack(body: QuarantinePackIn, db: Session = Depends(get_db),
                    user: models.User = Depends(require_roles("admin", "safety"))):
    pack = receiving.quarantine_pack(db, user=user, serial_no=body.serial_no, reason=body.reason)
    db.commit()
    return {"ok": True, "pack": pack_out(db, pack)}


@router.post("/quarantine/release")
def release_quarantine(body: ReleaseQuarantineIn, db: Session = Depends(get_db),
                       user: models.User = Depends(require_roles("admin", "safety"))):
    pack = receiving.release_quarantine(db, user=user, serial_no=body.serial_no, note=body.note)
    db.commit()
    return {"ok": True, "pack": pack_out(db, pack)}


@router.post("/quarantine/unfreeze-batch")
def unfreeze_batch(body: UnfreezeBatchIn, db: Session = Depends(get_db),
                   user: models.User = Depends(require_roles("admin"))):
    batch = receiving.unfreeze_batch(db, user=user, batch_no=body.batch_no, note=body.note)
    db.commit()
    return {"ok": True, "batch": batch_out(db, batch)}


@router.get("/quarantine")
def list_quarantine(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.scalars(select(models.QuarantineRecord).order_by(models.QuarantineRecord.id)).all()
    return [quarantine_out(db, q) for q in rows]
