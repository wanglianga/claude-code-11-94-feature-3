"""拆解服务：工单、双方见证扫码、换标、未知模组隔离"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..enums import ModuleStatus, PackStatus, WorkOrderStatus
from . import audit
from .errors import BusinessRuleError, NotFoundError


def _get_pack(db: Session, serial_no: str) -> models.Pack:
    pack = db.scalar(select(models.Pack).where(models.Pack.serial_no == serial_no))
    if not pack:
        raise NotFoundError(f"包 {serial_no} 不存在")
    return pack


def create_work_order(db: Session, *, user: models.User, serial_no: str, note: str = "") -> models.WorkOrder:
    pack = _get_pack(db, serial_no)
    if pack.frozen or pack.status == PackStatus.quarantined.value:
        raise BusinessRuleError(f"包 {serial_no} 处于隔离状态，不能开拆解工单")
    existing = db.scalar(
        select(models.WorkOrder).where(
            models.WorkOrder.pack_id == pack.id,
            models.WorkOrder.status.in_([
                WorkOrderStatus.created.value,
                WorkOrderStatus.in_progress.value,
                WorkOrderStatus.pending_verification.value,
            ]),
        )
    )
    if existing:
        raise BusinessRuleError("该包已有未完成工单")
    if pack.status == PackStatus.outbound.value:
        raise BusinessRuleError("已出库包不能再拆解")
    order = models.WorkOrder(pack_id=pack.id, status=WorkOrderStatus.created.value, note=note)
    db.add(order)
    pack.status = PackStatus.dismantling.value
    audit.log(db, user.id, "create_work_order", "work_order", None, {"pack": serial_no})
    db.flush()
    return order


def link_module(
    db: Session,
    *,
    user: models.User,
    work_order_id: int,
    module_serial: str,
    witness1: models.User,
    witness2: models.User,
) -> models.Module:
    """双方见证扫码建立包→模组父子关系；两人不能为同一人。"""
    order = db.get(models.WorkOrder, work_order_id)
    if not order:
        raise NotFoundError("工单不存在")
    if witness1.id == witness2.id:
        raise BusinessRuleError("双方见证必须由两名不同操作者扫码确认")
    pack = db.get(models.Pack, order.pack_id)
    if pack.frozen:
        raise BusinessRuleError("包已被冻结，父子关系建立暂停")
    dup = db.scalar(select(models.Module).where(models.Module.serial_no == module_serial))
    if dup:
        raise BusinessRuleError(f"模组序列号 {module_serial} 已存在，不能重复建立关系")

    module = models.Module(
        serial_no=module_serial,
        pack_id=pack.id,
        work_order_id=order.id,
        status=ModuleStatus.linked.value,
        unknown_parent=False,
    )
    db.add(module)
    order.status = WorkOrderStatus.in_progress.value
    order.witness1_id = witness1.id
    order.witness2_id = witness2.id
    order.witnessed_at = datetime.now(timezone.utc)
    audit.log(
        db, user.id, "link_module", "module", None,
        {"module": module_serial, "pack": pack.serial_no, "witnesses": [witness1.username, witness2.username]},
    )
    db.flush()
    return module


def register_unknown_module(
    db: Session, *, user: models.User, work_order_id: int, module_serial: str, reason: str
) -> models.Module:
    """无法确认父子关系的模组：隔离待核，禁止自动归到最相似序列号。"""
    order = db.get(models.WorkOrder, work_order_id)
    if not order:
        raise NotFoundError("工单不存在")
    dup = db.scalar(select(models.Module).where(models.Module.serial_no == module_serial))
    if dup:
        raise BusinessRuleError(f"模组序列号 {module_serial} 已存在")
    module = models.Module(
        serial_no=module_serial,
        pack_id=None,
        work_order_id=order.id,
        status=ModuleStatus.quarantine_review.value,
        unknown_parent=True,
    )
    db.add(module)
    order.status = WorkOrderStatus.pending_verification.value
    audit.log(
        db, user.id, "register_unknown_module", "module", None,
        {"module": module_serial, "reason": reason, "work_order": work_order_id},
    )
    db.flush()
    return module


def resolve_unknown_module(
    db: Session, *, user: models.User, module_serial: str, parent_serial: str
) -> models.Module:
    """待核模组经人工核实后挂回父包（仍保留 unknown_parent 历史痕迹于审计日志）。"""
    module = db.scalar(select(models.Module).where(models.Module.serial_no == module_serial))
    if not module or not module.unknown_parent:
        raise NotFoundError("待核模组不存在或已核实")
    pack = _get_pack(db, parent_serial)
    module.pack_id = pack.id
    module.unknown_parent = False
    module.status = ModuleStatus.linked.value
    order = db.get(models.WorkOrder, module.work_order_id)
    if order and order.status == WorkOrderStatus.pending_verification.value:
        order.status = WorkOrderStatus.in_progress.value
    audit.log(db, user.id, "resolve_unknown_module", "module", module.id,
              {"module": module_serial, "parent": parent_serial})
    db.flush()
    return module


def relabel(
    db: Session,
    *,
    user: models.User,
    entity_type: str,
    old_serial: str,
    new_serial: str,
    operator1: models.User,
    operator2: models.User | None,
    confirm: bool,
) -> models.LabelHistory:
    """重贴标签：保留旧号、操作者、时间；必须两人分别确认后才生效。

    第一次调用（confirm=False, operator2=None）只登记申请；
    第二名操作者调用 confirm=True 才真正改号。
    """
    if entity_type == "pack":
        entity = db.scalar(select(models.Pack).where(models.Pack.serial_no == old_serial))
    elif entity_type == "module":
        entity = db.scalar(select(models.Module).where(models.Module.serial_no == old_serial))
    else:
        raise BusinessRuleError("entity_type 只能是 pack 或 module")
    if not entity:
        raise NotFoundError(f"序列号 {old_serial} 不存在")

    pending = db.scalar(
        select(models.LabelHistory).where(
            models.LabelHistory.entity_type == entity_type,
            models.LabelHistory.old_serial == old_serial,
            models.LabelHistory.confirmed.is_(False),
        )
    )

    if not confirm or operator2 is None:
        if pending:
            raise BusinessRuleError("该标签已有待确认的换标申请，等待第二人确认")
        history = models.LabelHistory(
            entity_type=entity_type, entity_id=entity.id,
            old_serial=old_serial, new_serial=new_serial,
            operator1_id=operator1.id, confirmed=False,
        )
        db.add(history)
        audit.log(db, user.id, "relabel_request", entity_type, entity.id,
                  {"old": old_serial, "new": new_serial})
        db.flush()
        return history

    if not pending:
        raise BusinessRuleError("不存在待确认的换标申请，须先由第一名操作者发起")
    # 第二人确认：发起人以申请记录中的 operator1 为准
    initiator = db.get(models.User, pending.operator1_id)
    if initiator.id == operator2.id:
        raise BusinessRuleError("换标必须由两名不同操作者分别确认")
    if pending.new_serial != new_serial:
        raise BusinessRuleError("确认时的新序列号与申请不一致")
    # 第二人确认 -> 生效
    conflict = None
    if entity_type == "pack":
        conflict = db.scalar(select(models.Pack).where(models.Pack.serial_no == new_serial))
    else:
        conflict = db.scalar(select(models.Module).where(models.Module.serial_no == new_serial))
    if conflict:
        raise BusinessRuleError(f"新序列号 {new_serial} 已被占用")
    entity.serial_no = new_serial
    pending.operator2_id = operator2.id
    pending.confirmed = True
    pending.confirmed_at = datetime.now(timezone.utc)
    audit.log(db, user.id, "relabel_confirm", entity_type, entity.id,
              {"old": old_serial, "new": new_serial,
               "operators": [operator1.username, operator2.username]})
    db.flush()
    return pending


def complete_work_order(db: Session, *, user: models.User, work_order_id: int) -> models.WorkOrder:
    order = db.get(models.WorkOrder, work_order_id)
    if not order:
        raise NotFoundError("工单不存在")
    if order.status == WorkOrderStatus.pending_verification.value:
        raise BusinessRuleError("工单存在隔离待核模组，核实完成前不能关闭")
    pack = db.get(models.Pack, order.pack_id)
    order.status = WorkOrderStatus.completed.value
    if pack.status == PackStatus.dismantling.value:
        pack.status = PackStatus.pending_inspection.value
    audit.log(db, user.id, "complete_work_order", "work_order", order.id, {})
    db.flush()
    return order
