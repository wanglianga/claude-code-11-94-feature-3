"""仓库拣货、出库、下游签收、召回退运、批次核对"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models
from ..enums import (
    ApprovalDecision,
    BatchStatus,
    ModuleStatus,
    OutboundStatus,
    PackStatus,
    PickingStatus,
    ReleaseStatus,
)
from . import audit
from .errors import BusinessRuleError, NotFoundError


# ---------- 父子链重新校验（单包隔离策略下每次拆分/换标/出库必做） ----------

def revalidate_parent_chain(db: Session, pack: models.Pack) -> list[str]:
    """沿父子关系重新校验；返回问题列表。"""
    problems: list[str] = []
    if pack.frozen or pack.status == PackStatus.quarantined.value:
        problems.append(f"包 {pack.serial_no} 处于隔离/冻结")
    unknown = db.scalars(
        select(models.Module)
        .join(models.WorkOrder, models.WorkOrder.id == models.Module.work_order_id)
        .where(
            models.WorkOrder.pack_id == pack.id,
            models.Module.unknown_parent.is_(True),
        )
    ).all()
    for m in unknown:
        problems.append(f"模组 {m.serial_no} 父子关系未确认（隔离待核）")
    active_approval = db.scalar(
        select(models.Approval).where(
            models.Approval.pack_id == pack.id,
            models.Approval.status == ReleaseStatus.active.value,
        )
    )
    if not active_approval:
        problems.append("缺少有效放行单")
    return problems


# ---------- 仓库 ----------

def list_picking(db: Session) -> list[models.PickingOrder]:
    return list(db.scalars(select(models.PickingOrder).order_by(models.PickingOrder.id)).all())


def pick(db: Session, *, user: models.User, picking_id: int) -> models.PickingOrder:
    """仓库只能按已批准去向拣货；放行单失效后的待拣货单已被更正，不能拣。"""
    order = db.get(models.PickingOrder, picking_id)
    if not order:
        raise NotFoundError("拣货单不存在")
    if order.status != PickingStatus.waiting.value:
        raise BusinessRuleError(f"拣货单当前状态为 {order.status}，不能拣货")
    approval = db.get(models.Approval, order.approval_id)
    if approval.status != ReleaseStatus.active.value:
        order.status = PickingStatus.corrected.value
        order.correction_note = "放行单已失效，系统自动更正"
        db.flush()
        raise BusinessRuleError("对应放行单已失效，该拣货单已更正，禁止拣货")
    pack = db.get(models.Pack, order.pack_id)
    problems = revalidate_parent_chain(db, pack)
    if problems:
        raise BusinessRuleError("出库前父子链重新校验失败：" + "；".join(problems))

    order.status = PickingStatus.picked.value
    order.warehouse_id = user.id
    order.picked_at = datetime.now(timezone.utc)
    audit.log(db, user.id, "pick", "picking_order", order.id, {"pack": pack.serial_no})
    db.flush()
    return order


def ship(db: Session, *, user: models.User, outbound_id: int) -> models.OutboundOrder:
    """装车出库；装车后货物不能从历史删除，只能召回/退运。"""
    outbound = db.get(models.OutboundOrder, outbound_id)
    if not outbound:
        raise NotFoundError("出库单不存在")
    if outbound.status not in (OutboundStatus.created.value, OutboundStatus.notified.value):
        raise BusinessRuleError(f"出库单状态 {outbound.status}，不能装车")
    approval = db.get(models.Approval, outbound.approval_id)
    if approval.status != ReleaseStatus.active.value:
        raise BusinessRuleError("放行单已失效，不能出库")
    if outbound.quantity > (approval.quantity_limit or 0):
        raise BusinessRuleError("出库数量超过放行单限数量")
    pack = db.get(models.Pack, outbound.pack_id)
    problems = revalidate_parent_chain(db, pack)
    if problems:
        raise BusinessRuleError("出库前父子链重新校验失败：" + "；".join(problems))

    outbound.status = OutboundStatus.shipped.value
    outbound.shipped_at = datetime.now(timezone.utc)
    pack.status = PackStatus.outbound.value
    for m in db.scalars(select(models.Module).where(models.Module.pack_id == pack.id)).all():
        m.status = ModuleStatus.outbound.value
    audit.log(db, user.id, "ship", "outbound_order", outbound.id, {"pack": pack.serial_no})
    db.flush()
    return outbound


def sign_off(
    db: Session, *, user: models.User, outbound_id: int, action: str, signer: str, note: str = ""
) -> models.SignOff:
    """下游签收端：签收或拒收。拒收只能退回隔离待复核，不能自动回到可用库存。"""
    outbound = db.get(models.OutboundOrder, outbound_id)
    if not outbound:
        raise NotFoundError("出库单不存在")
    if outbound.status != OutboundStatus.shipped.value:
        raise BusinessRuleError("仅已装车出库的货物可以签收/拒收")
    record = models.SignOff(outbound_order_id=outbound.id, action=action, signer=signer, note=note)
    db.add(record)
    pack = db.get(models.Pack, outbound.pack_id)
    if action == "signed":
        outbound.status = OutboundStatus.signed.value
    elif action == "rejected":
        outbound.status = OutboundStatus.rejected.value
        # 退回隔离待复核——不自动回到可用库存
        pack.status = PackStatus.quarantined.value
        pack.frozen = True
        db.add(models.QuarantineRecord(
            batch_id=pack.batch_id, pack_id=pack.id, scope="single",
            reason=f"买家 {signer} 拒收：{note or '未说明'}，退回隔离待复核",
            operator_id=user.id,
        ))
        for m in db.scalars(select(models.Module).where(models.Module.pack_id == pack.id)).all():
            m.status = ModuleStatus.rejected_returned.value
        db.add(models.BuyerNotification(
            outbound_order_id=outbound.id, consignee=outbound.consignee,
            message=f"【拒收更正】收货人 {signer} 拒收包 {pack.serial_no}，货物已退回中心隔离待复核，不会自动回到可用库存。",
            corrected=True,
        ))
    else:
        raise BusinessRuleError("action 只能是 signed 或 rejected")
    audit.log(db, user.id, f"sign_off_{action}", "outbound_order", outbound.id, {"signer": signer})
    db.flush()
    return record


def recall_or_return(
    db: Session, *, user: models.User, outbound_id: int, kind: str, reason: str
) -> models.RecallOrder:
    """装车后的货物不能删除，须走召回或退运。"""
    if kind not in ("recall", "return"):
        raise BusinessRuleError("kind 只能是 recall 或 return")
    outbound = db.get(models.OutboundOrder, outbound_id)
    if not outbound:
        raise NotFoundError("出库单不存在")
    if outbound.status not in (OutboundStatus.shipped.value, OutboundStatus.signed.value):
        raise BusinessRuleError("只有已装车/已签收的货物可以召回或退运")
    order = models.RecallOrder(outbound_order_id=outbound.id, kind=kind, reason=reason, operator_id=user.id)
    db.add(order)
    outbound.status = OutboundStatus.recalled.value if kind == "recall" else OutboundStatus.returned.value
    pack = db.get(models.Pack, outbound.pack_id)
    pack.status = PackStatus.quarantined.value
    pack.frozen = True
    db.add(models.QuarantineRecord(
        batch_id=pack.batch_id, pack_id=pack.id, scope="single",
        reason=f"{'召回' if kind == 'recall' else '退运'}：{reason}", operator_id=user.id,
    ))
    audit.log(db, user.id, kind, "outbound_order", outbound.id, {"reason": reason})
    db.flush()
    return order


# ---------- 回收称重 ----------

def weigh_recycle(db: Session, *, user: models.User, serial_no: str, weight_kg: float) -> models.RecycleWeighing:
    if weight_kg <= 0:
        raise BusinessRuleError("称重必须大于 0")
    pack = db.scalar(select(models.Pack).where(models.Pack.serial_no == serial_no))
    module = db.scalar(select(models.Module).where(models.Module.serial_no == serial_no))
    if not pack and not module:
        raise NotFoundError(f"序列号 {serial_no} 不存在")
    record = models.RecycleWeighing(
        module_id=module.id if module else None,
        pack_id=pack.id if pack and not module else None,
        weight_kg=weight_kg, operator_id=user.id,
    )
    db.add(record)
    if pack and pack.status == PackStatus.pending_recycle.value:
        pack.status = PackStatus.outbound.value  # 回收处置完成视同出库离厂
    audit.log(db, user.id, "recycle_weighing", serial_no and "entity", None,
              {"serial": serial_no, "weight_kg": weight_kg})
    db.flush()
    return record


# ---------- 批次核对与结清 ----------

def compute_reconciliation(db: Session, batch: models.Batch) -> dict:
    pack_ids = [p.id for p in batch.packs]
    dismantled = db.scalar(
        select(func.count(models.Module.id)).where(models.Module.pack_id.in_(pack_ids))
    ) or 0
    unknown_modules = db.scalar(
        select(func.count(models.Module.id))
        .join(models.WorkOrder, models.WorkOrder.id == models.Module.work_order_id)
        .where(
            models.WorkOrder.pack_id.in_(pack_ids),
            models.Module.unknown_parent.is_(True),
        )
    ) or 0
    released = db.scalar(
        select(func.count(models.Approval.id)).where(
            models.Approval.pack_id.in_(pack_ids),
            models.Approval.status == ReleaseStatus.active.value,
            models.Approval.decision.in_([ApprovalDecision.echelon.value, ApprovalDecision.recycle.value]),
        )
    ) or 0
    shipped = db.scalar(
        select(func.count(models.OutboundOrder.id)).where(
            models.OutboundOrder.batch_id == batch.id,
            models.OutboundOrder.status.in_([
                OutboundStatus.shipped.value, OutboundStatus.signed.value,
                OutboundStatus.recalled.value, OutboundStatus.returned.value,
            ]),
        )
    ) or 0
    recycled_weight = db.scalar(
        select(func.coalesce(func.sum(models.RecycleWeighing.weight_kg), 0.0)).where(
            models.RecycleWeighing.pack_id.in_(pack_ids)
        )
    ) or 0.0
    # 放行数量与实际拆出数量、已发数量核对
    difference = released - shipped
    return {
        "dismantled_qty": dismantled,
        "unknown_modules": unknown_modules,
        "released_qty": released,
        "shipped_qty": shipped,
        "recycled_weight_kg": float(recycled_weight),
        "difference": difference,
    }


def close_batch(db: Session, *, user: models.User, batch_no: str, explanation: str | None = None) -> models.Batch:
    """差额未解释前阻止批次结清。"""
    batch = db.scalar(select(models.Batch).where(models.Batch.batch_no == batch_no))
    if not batch:
        raise NotFoundError(f"批次 {batch_no} 不存在")
    stats = compute_reconciliation(db, batch)

    blockers: list[str] = []
    if stats["unknown_modules"]:
        blockers.append(f"仍有 {stats['unknown_modules']} 个隔离待核模组未核实")
    if stats["difference"] != 0 and not explanation:
        blockers.append(
            f"放行数量 {stats['released_qty']} 与已发数量 {stats['shipped_qty']} 存在差额 "
            f"{stats['difference']}，未提供解释前不能结清"
        )
    frozen_packs = [p.serial_no for p in batch.packs if p.frozen]
    if frozen_packs:
        blockers.append("仍有冻结包：" + "、".join(frozen_packs))
    if blockers:
        raise BusinessRuleError("批次结清被阻止：" + "；".join(blockers), code="reconciliation_blocked")

    rec = models.Reconciliation(
        batch_id=batch.id,
        dismantled_qty=stats["dismantled_qty"],
        released_qty=stats["released_qty"],
        shipped_qty=stats["shipped_qty"],
        recycled_weight_kg=stats["recycled_weight_kg"],
        difference=stats["difference"],
        explained=stats["difference"] == 0 or bool(explanation),
        explanation=explanation,
    )
    db.add(rec)
    batch.status = BatchStatus.closed.value
    batch.closed = True
    audit.log(db, user.id, "close_batch", "batch", batch.id, stats)
    db.flush()
    return batch
