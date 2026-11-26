"""ORM 序列化"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .services.receiving import pending_preconditions


def _dt(v):
    return v.isoformat() if v else None


def user_out(u: models.User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name,
            "role": u.role, "team": u.team}


def batch_out(db: Session, b: models.Batch) -> dict:
    return {
        "id": b.id, "batch_no": b.batch_no, "oem": b.oem,
        "source_vehicle": b.source_vehicle, "status": b.status,
        "freeze_strategy": b.freeze_strategy, "closed": b.closed,
        "created_at": _dt(b.created_at),
        "pack_count": len(b.packs),
    }


def pack_out(db: Session, p: models.Pack, with_preconditions: bool = True) -> dict:
    data = {
        "id": p.id, "serial_no": p.serial_no, "batch_no": p.batch.batch_no,
        "oem": p.oem, "source_vehicle": p.source_vehicle, "status": p.status,
        "frozen": p.frozen, "quarantine_slot": p.quarantine_slot,
        "responsible_team": p.responsible_team, "created_at": _dt(p.created_at),
        "transport_events": [event_out(e) for e in p.transport_events],
        "modules": [{"id": m.id, "serial_no": m.serial_no, "status": m.status,
                     "unknown_parent": m.unknown_parent} for m in p.modules],
    }
    if with_preconditions:
        data["pending_preconditions"] = pending_preconditions(db, p)
    return data


def event_out(e: models.TransportEvent) -> dict:
    return {"id": e.id, "event_type": e.event_type, "description": e.description,
            "source_doc": e.source_doc, "case_closed": e.case_closed,
            "occurred_at": _dt(e.occurred_at)}


def receipt_out(db: Session, r: models.Receipt) -> dict:
    pack = db.get(models.Pack, r.pack_id)
    return {
        "id": r.id, "pack": pack_out(db, pack), "scan_payload": r.scan_payload,
        "quarantine_slot": r.quarantine_slot, "responsible_team": r.responsible_team,
        "notes": r.notes, "created_at": _dt(r.created_at),
        "pending_preconditions": pending_preconditions(db, pack),
    }


def work_order_out(db: Session, w: models.WorkOrder) -> dict:
    pack = db.get(models.Pack, w.pack_id)
    w1 = db.get(models.User, w.witness1_id) if w.witness1_id else None
    w2 = db.get(models.User, w.witness2_id) if w.witness2_id else None
    return {
        "id": w.id, "pack_serial": pack.serial_no, "status": w.status, "note": w.note,
        "witness1": user_out(w1) if w1 else None,
        "witness2": user_out(w2) if w2 else None,
        "witnessed_at": _dt(w.witnessed_at), "created_at": _dt(w.created_at),
    }


def module_out(m: models.Module) -> dict:
    return {"id": m.id, "serial_no": m.serial_no, "pack_id": m.pack_id,
            "work_order_id": m.work_order_id, "status": m.status,
            "unknown_parent": m.unknown_parent, "created_at": _dt(m.created_at)}


def label_out(h: models.LabelHistory) -> dict:
    return {"id": h.id, "entity_type": h.entity_type, "entity_id": h.entity_id,
            "old_serial": h.old_serial, "new_serial": h.new_serial,
            "operator1_id": h.operator1_id, "operator2_id": h.operator2_id,
            "confirmed": h.confirmed, "created_at": _dt(h.created_at),
            "confirmed_at": _dt(h.confirmed_at)}


def device_out(d: models.Device) -> dict:
    return {"id": d.id, "device_no": d.device_no, "name": d.name,
            "calibrated_until": _dt(d.calibrated_until)}


def inspection_out(db: Session, r: models.InspectionRecord) -> dict:
    d = db.get(models.Device, r.device_id)
    return {"id": r.id, "pack_id": r.pack_id, "device": device_out(d),
            "is_reinspection": r.is_reinspection, "insulation_pass": r.insulation_pass,
            "bms_reading_ok": r.bms_reading_ok, "result": r.result, "note": r.note,
            "created_at": _dt(r.created_at)}


def approval_out(db: Session, a: models.Approval) -> dict:
    pack = db.get(models.Pack, a.pack_id)
    approver = db.get(models.User, a.approver_id)
    return {"id": a.id, "pack_serial": pack.serial_no, "version": a.version,
            "decision": a.decision, "status": a.status, "purpose": a.purpose,
            "consignee": a.consignee, "quantity_limit": a.quantity_limit,
            "approver": user_out(approver), "rationale": a.rationale,
            "voided_reason": a.voided_reason, "created_at": _dt(a.created_at),
            "voided_at": _dt(a.voided_at)}


def picking_out(db: Session, po: models.PickingOrder) -> dict:
    approval = db.get(models.Approval, po.approval_id)
    pack = db.get(models.Pack, po.pack_id)
    return {"id": po.id, "approval_id": po.approval_id, "pack_serial": pack.serial_no,
            "decision": approval.decision, "approval_status": approval.status,
            "status": po.status, "correction_note": po.correction_note,
            "created_at": _dt(po.created_at), "picked_at": _dt(po.picked_at)}


def outbound_out(db: Session, o: models.OutboundOrder) -> dict:
    return {"id": o.id, "approval_id": o.approval_id,
            "pack_serial": db.get(models.Pack, o.pack_id).serial_no,
            "batch_no": db.get(models.Batch, o.batch_id).batch_no,
            "quantity": o.quantity, "purpose": o.purpose, "consignee": o.consignee,
            "status": o.status, "created_at": _dt(o.created_at),
            "shipped_at": _dt(o.shipped_at)}


def notification_out(n: models.BuyerNotification) -> dict:
    return {"id": n.id, "outbound_order_id": n.outbound_order_id,
            "consignee": n.consignee, "message": n.message, "corrected": n.corrected,
            "created_at": _dt(n.created_at)}


def signoff_out(s: models.SignOff) -> dict:
    return {"id": s.id, "outbound_order_id": s.outbound_order_id, "action": s.action,
            "signer": s.signer, "note": s.note, "created_at": _dt(s.created_at)}


def quarantine_out(db: Session, q: models.QuarantineRecord) -> dict:
    pack = db.get(models.Pack, q.pack_id) if q.pack_id else None
    return {"id": q.id, "batch_id": q.batch_id, "pack_serial": pack.serial_no if pack else None,
            "scope": q.scope, "reason": q.reason, "released": q.released,
            "release_note": q.release_note, "created_at": _dt(q.created_at)}
