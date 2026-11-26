"""L-7 场景仿真：整批隔离 vs 单包隔离策略对比，以及迟到浸水/换标失配注入。

仿真在独立事务中运行并回滚，不污染已提交的种子数据，可重复执行。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..enums import OutboundStatus, PackStatus
from . import dismantling, receiving, safety, warehouse
from .errors import BusinessRuleError


def _pack_map(db: Session) -> dict[str, models.Pack]:
    return {p.serial_no: p for p in db.scalars(select(models.Pack)).all()}


def _snapshot(db: Session) -> dict:
    packs = [
        {"serial_no": p.serial_no, "status": p.status, "frozen": p.frozen,
         "quarantine_slot": p.quarantine_slot}
        for p in db.scalars(select(models.Pack).order_by(models.Pack.serial_no)).all()
    ]
    approvals = [
        {"pack_id": a.pack_id, "decision": a.decision, "status": a.status,
         "version": a.version, "voided_reason": a.voided_reason}
        for a in db.scalars(select(models.Approval)).all()
    ]
    picking = [
        {"pack_id": po.pack_id, "status": po.status, "correction_note": po.correction_note}
        for po in db.scalars(select(models.PickingOrder)).all()
    ]
    notifications = [
        {"consignee": n.consignee, "message": n.message, "corrected": n.corrected}
        for n in db.scalars(select(models.BuyerNotification)).all()
    ]
    modules = [
        {"serial_no": m.serial_no, "pack_id": m.pack_id, "status": m.status,
         "unknown_parent": m.unknown_parent}
        for m in db.scalars(select(models.Module)).all()
    ]
    work_orders = [
        {"id": w.id, "pack_id": w.pack_id, "status": w.status}
        for w in db.scalars(select(models.WorkOrder)).all()
    ]
    quarantines = [
        {"scope": q.scope, "pack_id": q.pack_id, "reason": q.reason}
        for q in db.scalars(select(models.QuarantineRecord)).all()
    ]
    return {
        "packs": packs,
        "approvals": approvals,
        "picking_orders": picking,
        "notifications": notifications,
        "modules": modules,
        "work_orders": work_orders,
        "quarantine_records": quarantines,
    }


def _try_approve_echelon(db, user, pack: models.Pack) -> dict:
    try:
        safety.approve(
            db, user=user, serial_no=pack.serial_no, decision="echelon",
            purpose="储能调峰", consignee="华东储能公司", quantity_limit=1,
            rationale="场景仿真",
        )
        return {"pack": pack.serial_no, "result": "approved"}
    except BusinessRuleError as exc:
        return {"pack": pack.serial_no, "result": "blocked", "reason": exc.message}


def simulate_batch_freeze(db_factory, users: dict[str, models.User]) -> dict:
    """策略一：整批冻结。一包待查挡住所有无关包。"""
    db: Session = db_factory()
    try:
        safety_user = users["safety"]
        receiving.freeze_batch(db, user=users["admin"], batch_no="L-7",
                               reason="同车到货，先整批冻结核验身份与风险边界")
        attempts = []
        for serial in ("P-1", "P-2", "P-3", "P-4"):
            pack = _pack_map(db)[serial]
            attempts.append(_try_approve_echelon(db, safety_user, pack))
        snap = _snapshot(db)
        snap["approval_attempts"] = attempts
        snap["releasable"] = [a["pack"] for a in attempts if a["result"] == "approved"]
        snap["picking_count"] = len(snap["picking_orders"])
        snap["buyer_notification_count"] = len(snap["notifications"])
        return snap
    finally:
        db.rollback()
        db.close()


def simulate_single_pack(db_factory, users: dict[str, models.User]) -> dict:
    """策略二：单包隔离。证据齐全者先流转；每次拆分/换标/出库沿父子链重校验。"""
    db: Session = db_factory()
    try:
        # --- 阶段 0：仅隔离有碰撞记录且未复检的 P-1 ---
        receiving.quarantine_pack(db, user=users["admin"], serial_no="P-1",
                                  reason="P-1 有碰撞记录且未复检，单包隔离")
        initial_attempts = []
        for serial in ("P-1", "P-2", "P-3", "P-4"):
            initial_attempts.append(_try_approve_echelon(db, users["safety"], _pack_map(db)[serial]))
        initial = _snapshot(db)
        initial["approval_attempts"] = initial_attempts
        initial["releasable"] = [a["pack"] for a in initial_attempts if a["result"] == "approved"]

        # --- 阶段 1：P-3 出库前收到迟到的浸水回执 ---
        p3 = _pack_map(db)["P-3"]
        db.add(models.TransportEvent(
            pack_id=p3.id, event_type="water",
            description="运输商迟到回执：途中淋雨浸水", source_doc="WATER-LATE-001",
        ))
        db.flush()
        receiving.quarantine_pack(db, user=users["safety"], serial_no="P-3",
                                  reason="迟到浸水回执，暂停 P-3 出库并退回补检")
        # 旧放行单失效、拣货单更正、买家收到更正通知
        safety.approve(db, user=users["safety"], serial_no="P-3", decision="reinspect",
                       rationale="迟到浸水回执，须补检；原梯次利用放行依据失效")
        after_late_water = _snapshot(db)

        # 尝试继续拣 P-3 的货 -> 必须被阻止
        p3_picking = db.scalar(
            select(models.PickingOrder).join(models.Approval).where(
                models.Approval.pack_id == p3.id
            )
        )
        pick_attempt = None
        if p3_picking:
            try:
                warehouse.pick(db, user=users["warehouse"], picking_id=p3_picking.id)
                pick_attempt = {"result": "picked（异常：不应发生）"}
            except BusinessRuleError as exc:
                pick_attempt = {"result": "blocked", "reason": exc.message}
        after_late_water["p3_pick_attempt"] = pick_attempt

        # P-2/P-4 不受影响，仍可拣货出库
        unaffected = []
        for serial in ("P-2", "P-4"):
            pack = _pack_map(db)[serial]
            po = db.scalar(select(models.PickingOrder).where(models.PickingOrder.pack_id == pack.id))
            if po and po.status == "waiting":
                warehouse.pick(db, user=users["warehouse"], picking_id=po.id)
                unaffected.append(serial)
        after_late_water["still_flowing_packs"] = unaffected

        # --- 阶段 2：P-1 拆解发现无法匹配的重贴标签 ---
        # P-1 身份核实后解除单包隔离进入拆解（碰撞未复检仍会在梯次利用门禁处拦截）
        receiving.release_quarantine(db, user=users["admin"], serial_no="P-1",
                                     note="身份链核实完成，解除隔离进入拆解；碰撞复检仍为前置项")
        wo = dismantling.create_work_order(db, user=users["dismantler"], serial_no="P-1",
                                           note="P-1 拆解工单")
        unknown = dismantling.register_unknown_module(
            db, user=users["dismantler"], work_order_id=wo.id,
            module_serial="M-UNKNOWN-9", reason="模组重贴标签与任何在档序列号均不匹配，无法确认父子关系"
        )
        close_attempt = None
        try:
            dismantling.complete_work_order(db, user=users["dismantler"], work_order_id=wo.id)
            close_attempt = {"result": "completed（异常：不应发生）"}
        except BusinessRuleError as exc:
            close_attempt = {"result": "blocked", "reason": exc.message}
        after_relabel = _snapshot(db)
        after_relabel["work_order_close_attempt"] = close_attempt
        after_relabel["unknown_module"] = {
            "serial_no": unknown.serial_no, "pack_id": unknown.pack_id,
            "status": unknown.status, "unknown_parent": unknown.unknown_parent,
        }

        return {
            "initial_approval": initial,
            "after_late_water_p3": after_late_water,
            "after_relabel_mismatch_p1": after_relabel,
            "releasable_at_start": initial["releasable"],
            "picking_count_at_start": len(initial["picking_orders"]),
            "buyer_notification_count_at_start": len(initial["notifications"]),
        }
    finally:
        db.rollback()
        db.close()


def run_comparison(db_factory, users: dict[str, models.User]) -> dict:
    return {
        "batch_freeze_strategy": simulate_batch_freeze(db_factory, users),
        "single_pack_strategy": simulate_single_pack(db_factory, users),
        "conclusion": {
            "batch_freeze": "整批冻结下 P-1~P-4 全部不可放行，待拣货单与买家通知均为 0；无关包被一同挡住。",
            "single_pack": "单包隔离下 P-2/P-3/P-4 身份链完整、检测合格，可先行批准并生成拣货单与买家通知；"
                           "P-3 迟到浸水后仅暂停 P-3，旧放行单失效并同步更正拣货单与买家，P-2/P-4 继续流转；"
                           "P-1 的失配模组进隔离待核、工单挂起，绝不自动归到最相似序列号。",
        },
    }
