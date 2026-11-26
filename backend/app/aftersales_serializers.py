"""售后模块序列化：聚合案件全量状态，并实时计算剩余承诺/逾期/停机时长。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .services.aftersales import closure_blockers, warranty_view


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _remaining(deadline: datetime | None, now: datetime) -> dict | None:
    if not deadline:
        return None
    delta = deadline - now
    seconds = int(delta.total_seconds())
    overdue = seconds < 0
    abs_s = abs(seconds)
    days, rem = divmod(abs_s, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days > 0:
        text = (f"逾期 {days} 天 {hours} 小时" if overdue
                else f"剩余 {days} 天 {hours} 小时")
    elif hours > 0:
        text = (f"逾期 {hours} 小时 {minutes} 分" if overdue
                else f"剩余 {hours} 小时 {minutes} 分")
    else:
        text = (f"逾期 {minutes} 分钟" if overdue else f"剩余 {minutes} 分钟")
    return {"deadline": deadline.isoformat(), "seconds": seconds,
            "overdue": overdue, "text": text}


def _downtime(case: models.AftersalesCase, now: datetime) -> dict | None:
    if not case.downtime_started_at:
        return None
    end = case.downtime_ended_at or now
    seconds = int((end - case.downtime_started_at).total_seconds())
    hours = round(seconds / 3600, 1)
    return {
        "started_at": _iso(case.downtime_started_at),
        "ended_at": _iso(case.downtime_ended_at),
        "ongoing": case.downtime_ended_at is None,
        "seconds": seconds,
        "hours": hours,
        "text": (f"已停机 {hours} 小时（进行中）" if case.downtime_ended_at is None
                 else f"停机 {hours} 小时（已恢复）"),
    }


def deposit_out(dep: models.Deposit | None) -> dict | None:
    if not dep:
        return None
    return {
        "id": dep.id, "amount": dep.amount, "status": dep.status,
        "gateway_ref": dep.gateway_ref, "paid_at": _iso(dep.paid_at),
        "refund_requested_at": _iso(dep.refund_requested_at),
        "unknown_since": _iso(dep.unknown_since),
        "refunded_at": _iso(dep.refunded_at), "query_count": dep.query_count,
    }


def case_summary(db: Session, case: models.AftersalesCase) -> dict:
    now = models.utcnow()
    ret = db.scalar(select(models.OldPartReturn).where(
        models.OldPartReturn.case_id == case.id))
    overdue_return = bool(ret and ret.due_at and ret.status != "received" and now > ret.due_at)
    blockers = closure_blockers(db, case) if not case.closed else []
    return {
        "id": case.id, "case_no": case.case_no, "customer_code": case.customer_code,
        "title": case.title, "path": case.path, "status": case.status,
        "closed": case.closed,
        "module_serial": case.module_serial, "module_model": case.module_model,
        "liability_status": case.liability_status,
        "materials_complete": case.materials_complete,
        "custodian_party": case.custodian_party, "custodian_name": case.custodian_name,
        "payment_held": case.payment_held, "payment_resolved": case.payment_resolved,
        "downtime": _downtime(case, now),
        "commitment": _remaining(case.commitment_deadline, now),
        "next_contact": {
            "at": _iso(case.next_contact_at),
            "note": case.next_contact_note,
            **({"overdue": case.next_contact_at is not None and case.next_contact_at < now}
               if case.next_contact_at else {"overdue": False}),
        },
        "return_status": ret.status if ret else None,
        "return_overdue": overdue_return,
        "closure_blocker_count": len(blockers),
        "warranty": warranty_view(case),
        "created_at": _iso(case.created_at),
    }


def case_detail(db: Session, case: models.AftersalesCase) -> dict:
    now = models.utcnow()
    base = case_summary(db, case)

    checks = db.scalars(select(models.EngineeringCheck).where(
        models.EngineeringCheck.case_id == case.id).order_by(models.EngineeringCheck.id)).all()
    contacts = db.scalars(select(models.CaseContact).where(
        models.CaseContact.case_id == case.id).order_by(models.CaseContact.id.desc())).all()
    custody = db.scalars(select(models.CustodyEvent).where(
        models.CustodyEvent.case_id == case.id).order_by(models.CustodyEvent.id.desc())).all()
    orders = db.scalars(select(models.ReplacementOrder).where(
        models.ReplacementOrder.case_id == case.id).order_by(models.ReplacementOrder.id)).all()
    ret = db.scalar(select(models.OldPartReturn).where(
        models.OldPartReturn.case_id == case.id))
    insp = db.scalar(select(models.ReworkInspection).where(
        models.ReworkInspection.case_id == case.id))
    repairs = db.scalars(select(models.RepairRecord).where(
        models.RepairRecord.case_id == case.id).order_by(models.RepairRecord.id)).all()
    dep = db.scalar(select(models.Deposit).where(models.Deposit.case_id == case.id))

    def user_name(uid):
        if not uid:
            return None
        u = db.get(models.User, uid)
        return u.display_name if u else None

    base.update({
        "accepted_at": _iso(case.accepted_at),
        "original_appeal": case.original_appeal,
        "engineering_explanation": case.engineering_explanation,
        "liability_basis": case.liability_basis,
        "liability_at": _iso(case.liability_at),
        "materials_note": case.materials_note,
        "payment_hold_reason": case.payment_hold_reason,
        "payment_resolution": case.payment_resolution,
        "commitment_deadline": _iso(case.commitment_deadline),
        "commitment_note": case.commitment_note,
        "closed_at": _iso(case.closed_at),
        "closure_note": case.closure_note,
        "closure_blockers": closure_blockers(db, case) if not case.closed else [],
        "engineering_checks": [{
            "id": c.id, "kind": c.kind, "title": c.title, "description": c.description,
            "status": c.status, "result": c.result, "conclusion": c.conclusion,
            "engineer_name": user_name(c.engineer_id), "concluded_at": _iso(c.concluded_at),
        } for c in checks],
        "contacts": [{
            "id": c.id, "channel": c.channel, "note": c.note,
            "actor_name": user_name(c.actor_id), "created_at": _iso(c.created_at),
        } for c in contacts],
        "custody_events": [{
            "id": c.id, "scope": c.scope, "from_party": c.from_party, "to_party": c.to_party,
            "note": c.note, "actor_name": user_name(c.actor_id), "created_at": _iso(c.created_at),
        } for c in custody],
        "replacement_orders": [{
            "id": o.id, "plan_id": o.plan_id, "spare_serial": o.spare_serial,
            "demand_code": o.demand_code, "cost": o.cost,
            "shipment_status": o.shipment_status, "tracking_no": o.tracking_no,
            "shipped_at": _iso(o.shipped_at),
            "signoff_status": o.signoff_status, "signed_at": _iso(o.signed_at),
            "signer": o.signer,
        } for o in orders],
        "old_part_return": None if not ret else {
            "id": ret.id, "whole_serial": ret.whole_serial, "status": ret.status,
            "due_at": _iso(ret.due_at), "sent_at": _iso(ret.sent_at),
            "received_at": _iso(ret.received_at), "tracking_no": ret.tracking_no,
            "disposition": ret.disposition, "disposition_note": ret.disposition_note,
            "overdue": bool(ret.due_at and ret.status != "received" and ret.due_at < now),
        },
        "inspection": None if not insp else {
            "id": insp.id, "status": insp.status, "result": insp.result,
            "liability": insp.liability, "report": insp.report,
            "inspector_name": user_name(insp.inspector_id),
            "started_at": _iso(insp.started_at), "concluded_at": _iso(insp.concluded_at),
        },
        "repairs": [{
            "id": r.id, "old_whole_serial": r.old_whole_serial, "repair_kind": r.repair_kind,
            "actual_component_name": r.actual_component_name,
            "actual_component_serial": r.actual_component_serial, "quantity": r.quantity,
            "old_component_disposition": r.old_component_disposition,
            "whole_unit_whereabouts": r.whole_unit_whereabouts, "note": r.note,
            "technician_name": user_name(r.technician_id), "created_at": _iso(r.created_at),
        } for r in repairs],
        "deposit": deposit_out(dep),
    })
    return base


def plan_out(plan: models.AssignmentPlan) -> dict:
    return {
        "id": plan.id, "plan_no": plan.plan_no, "batch": plan.batch, "status": plan.status,
        "fulfilled_count": plan.fulfilled_count, "total_cost": plan.total_cost,
        "items": plan.items, "unmet": plan.unmet, "stats": plan.stats,
        "stale_reasons": plan.stale_reasons,
        "created_at": _iso(plan.created_at), "approved_at": _iso(plan.approved_at),
    }


def unit_out(u: models.SpareUnit) -> dict:
    return {
        "id": u.id, "serial_no": u.serial_no, "batch": u.batch,
        "model_code": u.model_code, "name": u.name, "status": u.status,
        "safety_released": u.safety_released, "qualification_note": u.qualification_note,
        "source": u.source, "whole_exchange_blocked": u.whole_exchange_blocked,
    }
