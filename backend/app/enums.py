import enum


class Role(str, enum.Enum):
    receiver = "receiver"          # 接收员
    dismantler = "dismantler"      # 拆解员
    safety = "safety"              # 安全工程师
    warehouse = "warehouse"        # 仓库
    downstream = "downstream"      # 下游买家（签收端）
    admin = "admin"                # 中心管理员（整批隔离等）


class PackStatus(str, enum.Enum):
    received = "received"            # 接收
    quarantined = "quarantined"      # 隔离
    dismantling = "dismantling"      # 拆解
    pending_inspection = "pending_inspection"  # 待检
    pending_approval = "pending_approval"      # 待审批
    reusable = "reusable"            # 可复用（梯次利用批准）
    pending_recycle = "pending_recycle"        # 待回收
    outbound = "outbound"            # 已出库


class BatchStatus(str, enum.Enum):
    open_batch = "open"
    frozen = "frozen"                # 整批隔离
    closed = "closed"                # 已结清


class InspectionResult(str, enum.Enum):
    pass_ = "pass"
    fail = "fail"
    pending = "pending"


class ApprovalDecision(str, enum.Enum):
    echelon = "echelon"              # 梯次利用
    recycle = "recycle"              # 回收
    reinspect = "reinspect"          # 退回补检（旧放行单失效）


class ReleaseStatus(str, enum.Enum):
    active = "active"
    voided = "voided"                # 退回补检后失效
    superseded = "superseded"        # 被新版本替代


class PickingStatus(str, enum.Enum):
    waiting = "waiting"              # 待拣货
    corrected = "corrected"          # 已更正（放行单失效后）
    picked = "picked"
    cancelled = "cancelled"


class OutboundStatus(str, enum.Enum):
    created = "created"              # 出库单已建（限数量/用途/收货人）
    notified = "notified"            # 已通知下游
    shipped = "shipped"              # 已装车出库
    rejected = "rejected"            # 买家拒收 -> 退回隔离待复核
    recalled = "recalled"            # 召回
    returned = "returned"            # 退运
    signed = "signed"                # 已签收


class Disposition(str, enum.Enum):
    echelon = "echelon"
    recycle = "recycle"
    quarantine_review = "quarantine_review"


class ModuleStatus(str, enum.Enum):
    linked = "linked"                       # 已建立父子关系
    quarantine_review = "quarantine_review"  # 隔离待核（父子关系无法确认）
    reusable = "reusable"                   # 可复用库存
    pending_recycle = "pending_recycle"     # 待回收
    outbound = "outbound"                   # 已出库
    rejected_returned = "rejected_returned"  # 拒收退回隔离待复核


class WorkOrderStatus(str, enum.Enum):
    created = "created"
    in_progress = "in_progress"
    pending_verification = "pending_verification"  # 待核工单
    completed = "completed"


class QuarantineScope(str, enum.Enum):
    batch = "batch"     # 整批隔离
    single = "single"   # 单包隔离


class TransportEventType(str, enum.Enum):
    collision = "collision"   # 碰撞
    water = "water"           # 浸水
    thermal = "thermal"       # 热事件
