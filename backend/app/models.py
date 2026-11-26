from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(32))
    team: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Batch(Base):
    """到货批次，如样例 L-7"""

    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    oem: Mapped[str] = mapped_column(String(128))
    source_vehicle: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="open")  # open|frozen|closed
    freeze_strategy: Mapped[str | None] = mapped_column(String(16), nullable=True)  # batch|single
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    packs: Mapped[list["Pack"]] = relationship(back_populates="batch")


class Pack(Base):
    """电池包：每包唯一序列号"""

    __tablename__ = "packs"

    id: Mapped[int] = mapped_column(primary_key=True)
    serial_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    oem: Mapped[str] = mapped_column(String(128))
    source_vehicle: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="received", index=True)
    quarantine_slot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    responsible_team: Mapped[str | None] = mapped_column(String(64), nullable=True)
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)  # 单包冻结标记
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    batch: Mapped["Batch"] = relationship(back_populates="packs")
    transport_events: Mapped[list["TransportEvent"]] = relationship(
        back_populates="pack", cascade="all, delete-orphan"
    )
    modules: Mapped[list["Module"]] = relationship(back_populates="pack")


class TransportEvent(Base):
    """运输中的碰撞 / 浸水 / 热事件记录（不可被 BMS 正常读数抵消）"""

    __tablename__ = "transport_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey("packs.id"))
    event_type: Mapped[str] = mapped_column(String(16))  # collision|water|thermal
    description: Mapped[str] = mapped_column(Text, default="")
    source_doc: Mapped[str] = mapped_column(String(128), default="")  # 回执编号
    case_closed: Mapped[bool] = mapped_column(Boolean, default=False)  # 热事件结案标记
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    pack: Mapped["Pack"] = relationship(back_populates="transport_events")


class Receipt(Base):
    """收货单：重复扫码只返回原单"""

    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey("packs.id"), unique=True)
    receiver_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    scan_payload: Mapped[str] = mapped_column(Text)
    quarantine_slot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    responsible_team: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QuarantineRecord(Base):
    """隔离记录：区分整批隔离与单包隔离"""

    __tablename__ = "quarantine_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    pack_id: Mapped[int | None] = mapped_column(ForeignKey("packs.id"), nullable=True)
    scope: Mapped[str] = mapped_column(String(16))  # batch|single
    reason: Mapped[str] = mapped_column(Text)
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    released: Mapped[bool] = mapped_column(Boolean, default=False)
    release_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkOrder(Base):
    """拆解工单"""

    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey("packs.id"))
    status: Mapped[str] = mapped_column(String(32), default="created")
    # created|in_progress|pending_verification|completed
    witness1_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    witness2_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    witnessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Module(Base):
    """模组：父子关系指向来源包；无法确认父子关系时隔离待核"""

    __tablename__ = "modules"
    __table_args__ = (UniqueConstraint("serial_no", name="uq_module_serial"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    serial_no: Mapped[str] = mapped_column(String(64), index=True)
    pack_id: Mapped[int | None] = mapped_column(ForeignKey("packs.id"), nullable=True)
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="linked")
    # linked|quarantine_review|reusable|pending_recycle|outbound|rejected_returned
    unknown_parent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    pack: Mapped["Pack | None"] = relationship(back_populates="modules")


class LabelHistory(Base):
    """重贴标签：保留旧号、操作者与时间，换标需两人分别确认"""

    __tablename__ = "label_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(16))  # pack|module
    entity_id: Mapped[int] = mapped_column(Integer)
    old_serial: Mapped[str] = mapped_column(String(64))
    new_serial: Mapped[str] = mapped_column(String(64))
    operator1_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    operator2_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Device(Base):
    """检测设备：含校准有效期"""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_no: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    calibrated_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InspectionRecord(Base):
    """检测台回执：绝缘测试、BMS 读数、复检结论"""

    __tablename__ = "inspection_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey("packs.id"))
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"))
    is_reinspection: Mapped[bool] = mapped_column(Boolean, default=False)
    insulation_pass: Mapped[bool] = mapped_column(Boolean)
    bms_reading_ok: Mapped[bool] = mapped_column(Boolean)
    result: Mapped[str] = mapped_column(String(16))  # pass|fail|pending
    inspector_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Approval(Base):
    """安全放行单（带版本；退回补检后旧单 voided，拣货单与买家通知同步更正）"""

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey("packs.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    decision: Mapped[str] = mapped_column(String(16))  # echelon|recycle|reinspect
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|voided|superseded
    purpose: Mapped[str | None] = mapped_column(String(128), nullable=True)       # 用途
    consignee: Mapped[str | None] = mapped_column(String(128), nullable=True)     # 收货人
    quantity_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)    # 限数量
    approver_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    rationale: Mapped[str] = mapped_column(Text, default="")
    voided_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PickingOrder(Base):
    """仓库拣货单：只能按已批准去向拣货"""

    __tablename__ = "picking_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    approval_id: Mapped[int] = mapped_column(ForeignKey("approvals.id"))
    pack_id: Mapped[int] = mapped_column(ForeignKey("packs.id"))
    status: Mapped[str] = mapped_column(String(16), default="waiting")
    # waiting|corrected|picked|cancelled
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    correction_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    picked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OutboundOrder(Base):
    """出库单：限数量、用途、收货人；装车后不可删除，只能召回/退运"""

    __tablename__ = "outbound_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    approval_id: Mapped[int] = mapped_column(ForeignKey("approvals.id"))
    pack_id: Mapped[int] = mapped_column(ForeignKey("packs.id"))
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(128))
    consignee: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="created")
    # created|notified|shipped|rejected|recalled|returned|signed
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BuyerNotification(Base):
    """下游买家通知；放行单失效时发送更正通知"""

    __tablename__ = "buyer_notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    outbound_order_id: Mapped[int] = mapped_column(ForeignKey("outbound_orders.id"))
    consignee: Mapped[str] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(Text)
    corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SignOff(Base):
    """下游签收端：签收或拒收（拒收只能退回隔离待复核）"""

    __tablename__ = "sign_offs"

    id: Mapped[int] = mapped_column(primary_key=True)
    outbound_order_id: Mapped[int] = mapped_column(ForeignKey("outbound_orders.id"))
    action: Mapped[str] = mapped_column(String(16))  # signed|rejected
    signer: Mapped[str] = mapped_column(String(128))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecycleWeighing(Base):
    """回收称重记录"""

    __tablename__ = "recycle_weighings"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int | None] = mapped_column(ForeignKey("modules.id"), nullable=True)
    pack_id: Mapped[int | None] = mapped_column(ForeignKey("packs.id"), nullable=True)
    weight_kg: Mapped[float] = mapped_column(Float)
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Reconciliation(Base):
    """批次数量核对：差额未解释前阻止批次结清"""

    __tablename__ = "reconciliations"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    dismantled_qty: Mapped[int] = mapped_column(Integer, default=0)   # 实际拆出数量
    released_qty: Mapped[int] = mapped_column(Integer, default=0)      # 放行数量
    shipped_qty: Mapped[int] = mapped_column(Integer, default=0)       # 已发数量
    recycled_weight_kg: Mapped[float] = mapped_column(Float, default=0.0)
    difference: Mapped[int] = mapped_column(Integer, default=0)
    explained: Mapped[bool] = mapped_column(Boolean, default=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecallOrder(Base):
    """召回 / 退运：装车货物不能删除，只能走召回或退运"""

    __tablename__ = "recall_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    outbound_order_id: Mapped[int] = mapped_column(ForeignKey("outbound_orders.id"))
    kind: Mapped[str] = mapped_column(String(16))  # recall|return
    reason: Mapped[str] = mapped_column(Text)
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """全链路审计日志"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ============================================================================
# 售后客服：保修申诉、两条办理路径、备件精确指派、实物/资金独立状态
# ============================================================================


class AftersalesCase(Base):
    """售后申诉案件（如客户 O-31）。

    保修窗口由虚构合同固定：验收日 00:00 起、次年对应日 00:00 前（右端开区间）。
    “在保”只是合同时间判断，责任必须由返修检测/工程补核结论证明。
    """

    __tablename__ = "as_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    customer_code: Mapped[str] = mapped_column(String(40), index=True)  # O-31
    title: Mapped[str] = mapped_column(String(200), default="")
    path: Mapped[str] = mapped_column(String(24), default="advance_replace")
    # advance_replace=先寄替换件后收旧件 | inspect_first=先收旧件复检后决定换货
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    # open|closed|withdrawn

    module_serial: Mapped[str] = mapped_column(String(64), index=True)  # 整机序列号
    module_model: Mapped[str] = mapped_column(String(64), default="PM-X3")
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))   # 验收时间
    warranty_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    warranty_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))   # 右端点（不含）
    appealed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    original_appeal: Mapped[str] = mapped_column(Text, default="")           # 原申诉，永久保留
    engineering_explanation: Mapped[str] = mapped_column(Text, default="")   # 工程解释，保留

    # 责任结论：undetermined 时任何备注都不算结论
    liability_status: Mapped[str] = mapped_column(String(20), default="undetermined")
    # undetermined|supplier|transport|customer|shared
    liability_basis: Mapped[str] = mapped_column(Text, default="")
    liability_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    liability_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 材料收齐
    materials_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    materials_note: Mapped[str] = mapped_column(Text, default="")

    # 客户停机时段
    downtime_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    downtime_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 服务承诺与下一次联系
    commitment_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    commitment_note: Mapped[str] = mapped_column(String(200), default="")
    next_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_contact_note: Mapped[str] = mapped_column(String(200), default="")

    # 当前保管人（由 CustodyEvent 流转）：customer|logistics|warehouse|lab
    custodian_party: Mapped[str] = mapped_column(String(20), default="customer")
    custodian_name: Mapped[str] = mapped_column(String(128), default="客户")

    # 先检路径的付款暂缓
    payment_held: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_hold_reason: Mapped[str] = mapped_column(Text, default="")
    payment_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_resolution: Mapped[str] = mapped_column(String(24), default="")  # released|deducted|waived

    closed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closure_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EngineeringCheck(Base):
    """工程人员补核项（运输压痕、缺失的安装温度回执等）。备注不能替代结论。"""

    __tablename__ = "as_engineering_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("as_cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # transport_dent|install_temp_receipt|other
    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|concluded
    result: Mapped[str | None] = mapped_column(String(16), nullable=True)  # confirmed|ruled_out
    conclusion: Mapped[str] = mapped_column(Text, default="")
    engineer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    concluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CaseContact(Base):
    """联系记录（每次沟通留痕，并可推进下一次联系时间）。"""

    __tablename__ = "as_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("as_cases.id"), index=True)
    channel: Mapped[str] = mapped_column(String(24), default="phone")  # phone|im|onsite|letter
    note: Mapped[str] = mapped_column(Text, default="")
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CustodyEvent(Base):
    """实物保管人流转台账（替换件/旧件分别记录）。"""

    __tablename__ = "as_custody_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("as_cases.id"), index=True)
    scope: Mapped[str] = mapped_column(String(16), default="old_part")  # old_part|replacement
    from_party: Mapped[str] = mapped_column(String(128), default="")
    to_party: Mapped[str] = mapped_column(String(128))
    note: Mapped[str] = mapped_column(Text, default="")
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Deposit(Base):
    """押金及其退款状态。退款通道结果未知是独立状态，不能当作已退。"""

    __tablename__ = "as_deposits"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("as_cases.id"), unique=True, index=True)
    amount: Mapped[int] = mapped_column(Integer, default=0)  # 整数元
    status: Mapped[str] = mapped_column(String(20), default="not_required", index=True)
    # not_required|pending|paid|refund_pending|refund_unknown|refunded|forfeited
    gateway_ref: Mapped[str] = mapped_column(String(64), default="")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refund_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unknown_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    query_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SpareUnit(Base):
    """备件实物（按序列号管理）。候选方案不占用，批准出库时才改状态。"""

    __tablename__ = "as_spare_units"
    __table_args__ = (UniqueConstraint("serial_no", name="uq_as_spare_serial"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    serial_no: Mapped[str] = mapped_column(String(64), index=True)
    batch: Mapped[str] = mapped_column(String(24), default="REAL", index=True)
    model_code: Mapped[str] = mapped_column(String(64), default="PM-X3")
    name: Mapped[str] = mapped_column(String(128), default="兼容替换模组")
    # available|allocated|shipped|installed|consumed
    status: Mapped[str] = mapped_column(String(16), default="available", index=True)
    safety_released: Mapped[bool] = mapped_column(Boolean, default=True)  # 安全资格/已放行
    qualification_note: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="stock")  # stock|restock|sample|rework
    # 只做过端子维修的整机：禁止再作为整机重复换出
    whole_exchange_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AssignDemand(Base):
    """指派批次中本批已批准（或复检后追加批准）的案件需求。"""

    __tablename__ = "as_assign_demands"
    __table_args__ = (UniqueConstraint("batch", "code", name="uq_as_demand_batch_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    batch: Mapped[str] = mapped_column(String(24), index=True)
    code: Mapped[str] = mapped_column(String(40))   # 稳定编号，如 D-O31 / R1 / J1
    case_id: Mapped[int | None] = mapped_column(ForeignKey("as_cases.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    approved: Mapped[bool] = mapped_column(Boolean, default=True)
    fulfilled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CompatEdge(Base):
    """固定兼容表 + 整数调配费用。"""

    __tablename__ = "as_compat_edges"
    __table_args__ = (UniqueConstraint("batch", "demand_code", "supply_code",
                                       name="uq_as_edge_triple"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    batch: Mapped[str] = mapped_column(String(24), index=True)
    demand_code: Mapped[str] = mapped_column(String(40), index=True)
    supply_code: Mapped[str] = mapped_column(String(64), index=True)
    cost: Mapped[int] = mapped_column(Integer, default=1)


class AssignmentPlan(Base):
    """一次精确搜索得到的候选方案。候选不占库存；批准时原子复核，过期则整案退回。"""

    __tablename__ = "as_assignment_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    batch: Mapped[str] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(String(16), default="candidate", index=True)
    # candidate|approved|stale
    fulfilled_count: Mapped[int] = mapped_column(Integer, default=0)
    total_cost: Mapped[int] = mapped_column(Integer, default=0)
    items: Mapped[list] = mapped_column(JSON, default=list)   # [{demand_code,supply_code,cost}]
    unmet: Mapped[list] = mapped_column(JSON, default=list)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)    # 分支数/耗时/空间等
    stale_reasons: Mapped[list] = mapped_column(JSON, default=list)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReplacementOrder(Base):
    """替换件出库/寄递单：①寄出 ②客户签收 为两个独立状态。

    spare_unit_id 唯一约束从数据库层杜绝同一整机序列号产生第二张换出单。
    """

    __tablename__ = "as_replacement_orders"
    __table_args__ = (UniqueConstraint("spare_unit_id", name="uq_as_repl_spare_once"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("as_cases.id"), nullable=True, index=True)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("as_assignment_plans.id"), nullable=True)
    spare_unit_id: Mapped[int] = mapped_column(ForeignKey("as_spare_units.id"))
    spare_serial: Mapped[str] = mapped_column(String(64), index=True)
    demand_code: Mapped[str] = mapped_column(String(40), default="")
    cost: Mapped[int] = mapped_column(Integer, default=0)

    shipment_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending|shipped
    tracking_no: Mapped[str] = mapped_column(String(64), default="")
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    shipped_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    signoff_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending|signed
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signer: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OldPartReturn(Base):
    """旧件回收：③回收状态独立。未实收（received）不能成为返修库存。"""

    __tablename__ = "as_old_part_returns"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("as_cases.id"), unique=True, index=True)
    whole_serial: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="not_sent", index=True)
    # not_sent|in_transit|received
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    tracking_no: Mapped[str] = mapped_column(String(64), default="")
    # 实物最终去向/处置，结清实物待办时必须非 pending
    disposition: Mapped[str] = mapped_column(String(24), default="pending")
    # pending|rework_stock|terminal_repair|repaired_returned|scrapped|returned_customer
    disposition_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReworkInspection(Base):
    """④返修检测：独立于签收/回收/退款的状态机。"""

    __tablename__ = "as_rework_inspections"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("as_cases.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="not_started", index=True)
    # not_started|in_progress|concluded
    result: Mapped[str | None] = mapped_column(String(24), nullable=True)
    # terminal_repairable|repairable|no_fault|fault_confirmed|scrap
    liability: Mapped[str] = mapped_column(String(20), default="undetermined")
    report: Mapped[str] = mapped_column(Text, default="")
    inspector_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    concluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RepairRecord(Base):
    """真实维修记录：只修端子时记录真实部件与旧件/整机去向。"""

    __tablename__ = "as_repair_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("as_cases.id"), index=True)
    old_whole_serial: Mapped[str] = mapped_column(String(64), index=True)
    repair_kind: Mapped[str] = mapped_column(String(20), default="terminal_only")
    # terminal_only|component_replace|whole_replace
    actual_component_name: Mapped[str] = mapped_column(String(128), default="")
    actual_component_serial: Mapped[str] = mapped_column(String(64), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    old_component_disposition: Mapped[str] = mapped_column(String(200), default="")
    whole_unit_whereabouts: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    technician_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
