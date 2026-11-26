"""收货与隔离服务"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..enums import BatchStatus, PackStatus, QuarantineScope
from . import audit
from .errors import BusinessRuleError, NotFoundError

# 收货单必须显示的未完成前置项
def pending_preconditions(db: Session, pack: models.Pack) -> list[str]:
    items: list[str] = []
    if not pack.quarantine_slot:
        items.append("未安排隔离位")
    if not pack.responsible_team:
        items.append("未指定责任班组")
    for ev in pack.transport_events:
        if ev.event_type == "collision":
            done = db.scalar(
                select(models.InspectionRecord).where(
                    models.InspectionRecord.pack_id == pack.id,
                    models.InspectionRecord.is_reinspection.is_(True),
                    models.InspectionRecord.result == "pass",
                )
            )
            if not done:
                items.append(f"碰撞记录（{ev.source_doc or ev.id}）尚未复检合格")
        if ev.event_type == "water":
            done = db.scalar(
                select(models.InspectionRecord).where(
                    models.InspectionRecord.pack_id == pack.id,
                    models.InspectionRecord.is_reinspection.is_(True),
                    models.InspectionRecord.result == "pass",
                )
            )
            if not done:
                items.append(f"浸水记录（{ev.source_doc or ev.id}）尚未复检合格")
        if ev.event_type == "thermal" and not ev.case_closed:
            items.append(f"热事件（{ev.source_doc or ev.id}）未结案")
    return items


def get_or_create_batch(db: Session, batch_no: str, oem: str, source_vehicle: str) -> models.Batch:
    batch = db.scalar(select(models.Batch).where(models.Batch.batch_no == batch_no))
    if batch:
        return batch
    batch = models.Batch(batch_no=batch_no, oem=oem, source_vehicle=source_vehicle)
    db.add(batch)
    db.flush()
    return batch


def find_receipt_by_serial(db: Session, serial_no: str) -> models.Receipt | None:
    """重复扫码：只返回原收货单"""
    pack = db.scalar(select(models.Pack).where(models.Pack.serial_no == serial_no))
    if not pack:
        return None
    return db.scalar(select(models.Receipt).where(models.Receipt.pack_id == pack.id))


def receive_pack(
    db: Session,
    *,
    user: models.User,
    batch_no: str,
    serial_no: str,
    oem: str,
    source_vehicle: str,
    scan_payload: str,
    quarantine_slot: str | None,
    responsible_team: str | None,
    events: list[dict],
    notes: str = "",
) -> tuple[models.Pack, models.Receipt, bool]:
    """返回 (pack, receipt, duplicated)；重复扫码只返回原收货单。"""
    existing = find_receipt_by_serial(db, serial_no)
    if existing:
        pack = db.get(models.Pack, existing.pack_id)
        return pack, existing, True

    batch = get_or_create_batch(db, batch_no, oem, source_vehicle)
    pack = models.Pack(
        serial_no=serial_no,
        batch_id=batch.id,
        oem=oem,
        source_vehicle=source_vehicle,
        status=PackStatus.received.value,
        quarantine_slot=quarantine_slot,
        responsible_team=responsible_team,
    )
    db.add(pack)
    db.flush()
    for ev in events or []:
        db.add(
            models.TransportEvent(
                pack_id=pack.id,
                event_type=ev["event_type"],
                description=ev.get("description", ""),
                source_doc=ev.get("source_doc", ""),
                case_closed=ev.get("case_closed", False),
            )
        )
    receipt = models.Receipt(
        pack_id=pack.id,
        receiver_id=user.id,
        scan_payload=scan_payload,
        quarantine_slot=quarantine_slot,
        responsible_team=responsible_team,
        notes=notes,
    )
    db.add(receipt)
    audit.log(db, user.id, "receive_pack", "pack", pack.id, {"serial_no": serial_no, "batch_no": batch_no})
    db.flush()
    return pack, receipt, False


def freeze_batch(db: Session, *, user: models.User, batch_no: str, reason: str) -> models.Batch:
    """整批隔离：同车货物全部冻结，减少串错，但无关包也被挡住。"""
    batch = db.scalar(select(models.Batch).where(models.Batch.batch_no == batch_no))
    if not batch:
        raise NotFoundError(f"批次 {batch_no} 不存在")
    if batch.closed:
        raise BusinessRuleError("批次已结清，不能再隔离")
    batch.status = BatchStatus.frozen.value
    batch.freeze_strategy = QuarantineScope.batch.value
    for pack in batch.packs:
        pack.status = PackStatus.quarantined.value
        pack.frozen = True
    db.add(
        models.QuarantineRecord(
            batch_id=batch.id, pack_id=None, scope=QuarantineScope.batch.value,
            reason=reason, operator_id=user.id,
        )
    )
    audit.log(db, user.id, "freeze_batch", "batch", batch.id, {"reason": reason})
    db.flush()
    return batch


def quarantine_pack(db: Session, *, user: models.User, serial_no: str, reason: str) -> models.Pack:
    """单包隔离：身份与风险边界核实后只冻结该包，其余证据齐全者可继续流转。"""
    pack = db.scalar(select(models.Pack).where(models.Pack.serial_no == serial_no))
    if not pack:
        raise NotFoundError(f"包 {serial_no} 不存在")
    if pack.status == PackStatus.outbound.value:
        raise BusinessRuleError("已出库包不能再设为隔离，须走召回或退运")
    pack.status = PackStatus.quarantined.value
    pack.frozen = True
    db.add(
        models.QuarantineRecord(
            batch_id=pack.batch_id, pack_id=pack.id, scope=QuarantineScope.single.value,
            reason=reason, operator_id=user.id,
        )
    )
    audit.log(db, user.id, "quarantine_pack", "pack", pack.id, {"reason": reason})
    db.flush()
    return pack


def release_quarantine(db: Session, *, user: models.User, serial_no: str, note: str) -> models.Pack:
    """解除单包隔离（风险边界核实完成）。整批冻结的批次需先解冻批次。"""
    pack = db.scalar(select(models.Pack).where(models.Pack.serial_no == serial_no))
    if not pack:
        raise NotFoundError(f"包 {serial_no} 不存在")
    batch = db.get(models.Batch, pack.batch_id)
    if batch.status == BatchStatus.frozen.value and batch.freeze_strategy == QuarantineScope.batch.value:
        raise BusinessRuleError("该包处于整批冻结中，须先由管理员解冻批次")
    pack.frozen = False
    if pack.status == PackStatus.quarantined.value:
        pack.status = PackStatus.received.value
    rec = db.scalar(
        select(models.QuarantineRecord).where(
            models.QuarantineRecord.pack_id == pack.id,
            models.QuarantineRecord.released.is_(False),
        )
    )
    if rec:
        rec.released = True
        rec.release_note = note
    audit.log(db, user.id, "release_quarantine", "pack", pack.id, {"note": note})
    db.flush()
    return pack


def unfreeze_batch(db: Session, *, user: models.User, batch_no: str, note: str) -> models.Batch:
    batch = db.scalar(select(models.Batch).where(models.Batch.batch_no == batch_no))
    if not batch:
        raise NotFoundError(f"批次 {batch_no} 不存在")
    batch.status = BatchStatus.open_batch.value
    for pack in batch.packs:
        # 仍有单包隔离记录的保持隔离
        single = db.scalar(
            select(models.QuarantineRecord).where(
                models.QuarantineRecord.pack_id == pack.id,
                models.QuarantineRecord.scope == QuarantineScope.single.value,
                models.QuarantineRecord.released.is_(False),
            )
        )
        pack.frozen = bool(single)
        if not single and pack.status == PackStatus.quarantined.value:
            pack.status = PackStatus.received.value
    audit.log(db, user.id, "unfreeze_batch", "batch", batch.id, {"note": note})
    db.flush()
    return batch
