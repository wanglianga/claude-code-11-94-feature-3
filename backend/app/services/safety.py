"""检测台回执与安全放行服务"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..enums import (
    ApprovalDecision,
    OutboundStatus,
    PackStatus,
    PickingStatus,
    ReleaseStatus,
)
from . import audit
from .errors import BusinessRuleError, NotFoundError


# ---------- 检测台 ----------

def add_device(db: Session, *, device_no: str, name: str, calibrated_until: datetime) -> models.Device:
    dev = db.scalar(select(models.Device).where(models.Device.device_no == device_no))
    if dev:
        return dev
    dev = models.Device(device_no=device_no, name=name, calibrated_until=calibrated_until)
    db.add(dev)
    db.flush()
    return dev


def submit_inspection(
    db: Session,
    *,
    user: models.User,
    serial_no: str,
    device_no: str,
    insulation_pass: bool,
    bms_reading_ok: bool,
    is_reinspection: bool = False,
    note: str = "",
) -> models.InspectionRecord:
    pack = db.scalar(select(models.Pack).where(models.Pack.serial_no == serial_no))
    if not pack:
        raise NotFoundError(f"包 {serial_no} 不存在")
    device = db.scalar(select(models.Device).where(models.Device.device_no == device_no))
    if not device:
        raise NotFoundError(f"设备 {device_no} 不存在")

    record = models.InspectionRecord(
        pack_id=pack.id,
        device_id=device.id,
        is_reinspection=is_reinspection,
        insulation_pass=insulation_pass,
        bms_reading_ok=bms_reading_ok,
        result="pass" if insulation_pass and bms_reading_ok else "fail",
        inspector_id=user.id,
        note=note,
    )
    db.add(record)
    if pack.status == PackStatus.pending_inspection.value and record.result == "pass":
        pack.status = PackStatus.pending_approval.value
    audit.log(db, user.id, "submit_inspection", "pack", pack.id,
              {"device": device_no, "result": record.result, "reinspection": is_reinspection})
    db.flush()
    return record


def calibration_valid(device: models.Device) -> bool:
    return device.calibrated_until > datetime.now(timezone.utc)


# ---------- 放行门禁 ----------

def echelon_blockers(db: Session, pack: models.Pack) -> list[str]:
    """梯次利用硬门禁；返回全部阻塞原因（空列表代表可批准）。"""
    blockers: list[str] = []

    # 1) 运输事件：碰撞 / 浸水必须有复检合格；热事件必须结案
    for ev in pack.transport_events:
        if ev.event_type in ("collision", "water"):
            reinspect = db.scalar(
                select(models.InspectionRecord).where(
                    models.InspectionRecord.pack_id == pack.id,
                    models.InspectionRecord.is_reinspection.is_(True),
                    models.InspectionRecord.result == "pass",
                )
            )
            if not reinspect:
                label = "碰撞" if ev.event_type == "collision" else "浸水"
                blockers.append(f"存在{label}记录（{ev.source_doc or ev.id}）且未完成复检合格——BMS 当前读数正常不能抵消历史事件")
        if ev.event_type == "thermal" and not ev.case_closed:
            blockers.append(f"热事件（{ev.source_doc or ev.id}）未结案")

    # 2) 最近一次检测回执：设备校准、绝缘测试
    latest = db.scalar(
        select(models.InspectionRecord)
        .where(models.InspectionRecord.pack_id == pack.id)
        .order_by(models.InspectionRecord.created_at.desc())
    )
    if not latest:
        blockers.append("缺少检测台回执")
    else:
        device = db.get(models.Device, latest.device_id)
        if not calibration_valid(device):
            blockers.append(f"检测设备 {device.device_no} 校准已于 {device.calibrated_until:%Y-%m-%d} 过期")
        if not latest.insulation_pass:
            blockers.append("绝缘测试失败")
        if latest.result != "pass":
            blockers.append("最近一次检测结论不合格")

    # 3) 父子链：与该包工单关联、但父子关系无法确认的模组不能放行
    unknown = db.scalar(
        select(models.Module)
        .join(models.WorkOrder, models.WorkOrder.id == models.Module.work_order_id)
        .where(
            models.WorkOrder.pack_id == pack.id,
            models.Module.unknown_parent.is_(True),
        )
    )
    if unknown:
        blockers.append(f"模组 {unknown.serial_no} 父子关系无法确认，处于隔离待核（工单挂起）")

    # 4) 隔离/冻结状态
    if pack.frozen or pack.status == PackStatus.quarantined.value:
        blockers.append("包处于隔离/冻结状态")
    return blockers


def _void_active_approvals(
    db: Session, *, pack: models.Pack, reason: str, approver: models.User
) -> list[models.Approval]:
    """退回补检：旧放行单失效，拣货单与已通知买家同步更正。"""
    actives = db.scalars(
        select(models.Approval).where(
            models.Approval.pack_id == pack.id,
            models.Approval.status == ReleaseStatus.active.value,
        )
    ).all()
    for approval in actives:
        approval.status = ReleaseStatus.voided.value
        approval.voided_reason = reason
        approval.voided_at = datetime.now(timezone.utc)

        for picking in db.scalars(
            select(models.PickingOrder).where(
                models.PickingOrder.approval_id == approval.id,
                models.PickingOrder.status == PickingStatus.waiting.value,
            )
        ).all():
            picking.status = PickingStatus.corrected.value
            picking.correction_note = f"放行单 #{approval.id} 已失效：{reason}"

        for outbound in db.scalars(
            select(models.OutboundOrder).where(
                models.OutboundOrder.approval_id == approval.id,
                models.OutboundOrder.status.in_([
                    OutboundStatus.created.value, OutboundStatus.notified.value,
                ]),
            )
        ).all():
            db.add(
                models.BuyerNotification(
                    outbound_order_id=outbound.id,
                    consignee=outbound.consignee,
                    message=f"【更正通知】出库单 #{outbound.id} 对应放行单已失效（{reason}），原通知作废，请勿提货。",
                    corrected=True,
                )
            )
        audit.log(db, approver.id, "void_approval", "approval", approval.id, {"reason": reason})
    return actives


def approve(
    db: Session,
    *,
    user: models.User,
    serial_no: str,
    decision: str,
    purpose: str | None = None,
    consignee: str | None = None,
    quantity_limit: int | None = None,
    rationale: str = "",
) -> models.Approval:
    pack = db.scalar(select(models.Pack).where(models.Pack.serial_no == serial_no))
    if not pack:
        raise NotFoundError(f"包 {serial_no} 不存在")

    if decision == ApprovalDecision.reinspect.value:
        # 退回补检是对风险的响应，允许在隔离中发起：旧放行单失效 + 状态回退到待检。
        # 历史碰撞/浸水事件仍在，复检合格前梯次利用门禁会继续拦截。
        voided = _void_active_approvals(
            db, pack=pack, reason=rationale or "安全工程师退回补检", approver=user
        )
        pack.status = PackStatus.pending_inspection.value
        pack.frozen = False
        open_q = db.scalars(
            select(models.QuarantineRecord).where(
                models.QuarantineRecord.pack_id == pack.id,
                models.QuarantineRecord.released.is_(False),
            )
        ).all()
        for q in open_q:
            q.released = True
            q.release_note = f"退回补检自动解除隔离：{rationale or '见放行单'}"
        approval = models.Approval(
            pack_id=pack.id, version=1, decision=decision, status=ReleaseStatus.active.value,
            approver_id=user.id, rationale=rationale,
        )
        db.add(approval)
        audit.log(db, user.id, "approve_reinspect", "pack", pack.id,
                  {"voided": [a.id for a in voided]})
        db.flush()
        return approval

    if pack.frozen or pack.status == PackStatus.quarantined.value:
        raise BusinessRuleError("包处于隔离/冻结状态，不能批准梯次利用或回收；如需补检请选择退回补检")

    if decision == ApprovalDecision.echelon.value:
        blockers = echelon_blockers(db, pack)
        if blockers:
            raise BusinessRuleError("梯次利用放行被阻止：" + "；".join(blockers), code="echelon_blocked")
        if not (purpose and consignee and quantity_limit and quantity_limit > 0):
            raise BusinessRuleError("梯次利用批准必须填写用途、收货人和正整数限数量")
        new_status = PackStatus.reusable.value
    elif decision == ApprovalDecision.recycle.value:
        new_status = PackStatus.pending_recycle.value
    else:
        raise BusinessRuleError(f"未知审批决定 {decision}")

    # 版本管理：同包新批准替代旧的有效单
    prev = db.scalars(
        select(models.Approval).where(
            models.Approval.pack_id == pack.id,
            models.Approval.status == ReleaseStatus.active.value,
        )
    ).all()
    version = (max((a.version for a in prev), default=0) + 1)
    for a in prev:
        a.status = ReleaseStatus.superseded.value

    approval = models.Approval(
        pack_id=pack.id, version=version, decision=decision, status=ReleaseStatus.active.value,
        purpose=purpose, consignee=consignee, quantity_limit=quantity_limit,
        approver_id=user.id, rationale=rationale,
    )
    db.add(approval)
    db.flush()
    pack.status = new_status

    # 自动生成仓库待拣货单（仓库只能按已批准去向拣货）
    db.add(models.PickingOrder(
        approval_id=approval.id, pack_id=pack.id, status=PickingStatus.waiting.value,
    ))

    # 梯次利用：批准后生成限数量/用途/收货人的出库单并通知买家
    if decision == ApprovalDecision.echelon.value:
        outbound = models.OutboundOrder(
            approval_id=approval.id, pack_id=pack.id, batch_id=pack.batch_id,
            quantity=quantity_limit, purpose=purpose, consignee=consignee,
            status=OutboundStatus.created.value, creator_id=user.id,
        )
        db.add(outbound)
        db.flush()
        db.add(models.BuyerNotification(
            outbound_order_id=outbound.id, consignee=consignee,
            message=f"【到货预告】包 {pack.serial_no} 已批准梯次利用，用途：{purpose}，数量：{quantity_limit}，收货人：{consignee}。",
        ))
        outbound.status = OutboundStatus.notified.value

    audit.log(db, user.id, "approve", "pack", pack.id,
              {"decision": decision, "version": version})
    db.flush()
    return approval
