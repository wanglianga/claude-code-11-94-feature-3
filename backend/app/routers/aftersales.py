"""售后客服 API：案件工作台、两条路径动作、精确指派工作台、五个演示场景支撑。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..aftersales_serializers import case_detail, case_summary, plan_out, unit_out
from ..database import get_db
from ..deps import get_current_user, require_roles
from ..seed_aftersales import seed_aftersales
from ..services import aftersales as svc
from ..services.errors import BusinessRuleError

router = APIRouter(prefix="/api/aftersales", tags=["aftersales"])

CS = ("service", "admin")            # 客服
ENG = ("engineer", "safety", "admin")
WH = ("warehouse", "admin")
FIN = ("finance", "service", "admin")


def _aware(dt: datetime | None) -> datetime | None:
    """datetime-local 提交的是北京墙钟时间（naive），补 +08:00 后再参与比较。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        from ..services.aftersales import CST
        return dt.replace(tzinfo=CST)
    return dt


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class ContactIn(BaseModel):
    channel: str = "phone"
    note: str = ""
    next_contact_at: datetime | None = None
    next_contact_note: str = ""


class ScheduleIn(BaseModel):
    commitment_deadline: datetime | None = None
    commitment_note: str | None = None
    next_contact_at: datetime | None = None
    next_contact_note: str | None = None


class ActionIn(BaseModel):
    action: str = "start"


class MaterialsIn(BaseModel):
    complete: bool = True
    note: str = ""


class CustodyIn(BaseModel):
    party: str
    name: str
    scope: str = "old_part"
    note: str = ""


class EngCheckIn(BaseModel):
    kind: str = "other"
    title: str
    description: str = ""


class ConcludeCheckIn(BaseModel):
    result: str
    conclusion: str


class LiabilityIn(BaseModel):
    liability: str
    rationale: str


class AmountIn(BaseModel):
    amount: int = 3000


class PayIn(BaseModel):
    amount: int | None = None
    gateway_ref: str = "POS-COUNTER"


class ReasonIn(BaseModel):
    reason: str = ""
    note: str = ""


class HoldIn(BaseModel):
    held: bool = True
    reason: str = ""


class ResolutionIn(BaseModel):
    resolution: str


class TrackingIn(BaseModel):
    tracking_no: str = ""


class InspectionConcludeIn(BaseModel):
    result: str
    liability: str = "undetermined"
    report: str


class RepairIn(BaseModel):
    repair_kind: str = "terminal_only"
    actual_component_name: str
    actual_component_serial: str = ""
    quantity: int = 1
    old_component_disposition: str = ""
    whole_unit_whereabouts: str
    note: str = ""
    final_disposition: str = "terminal_repair"


class CloseIn(BaseModel):
    note: str = ""


class ExchangeAssignIn(BaseModel):
    supply_serial: str
    cost: int = 1


class RestockIn(BaseModel):
    serial_no: str
    batch: str = "REAL"
    model_code: str = "PM-X3"
    name: str = "兼容替换模组"


class SafetyIn(BaseModel):
    released: bool = False
    note: str = ""


class EdgeIn(BaseModel):
    batch: str = "REAL"
    demand_code: str
    supply_code: str
    cost: int = 1


class ShipIn(BaseModel):
    tracking_no: str = ""


class SignIn(BaseModel):
    signer: str = "客户"


# ---------------------------------------------------------------------------
# 案件读取
# ---------------------------------------------------------------------------

@router.get("/cases")
def list_cases(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.scalars(select(models.AftersalesCase).order_by(models.AftersalesCase.id)).all()
    return [case_summary(db, c) for c in rows]


@router.get("/cases/{case_no}")
def get_case(case_no: str, db: Session = Depends(get_db),
             _: models.User = Depends(get_current_user)):
    return case_detail(db, svc.get_case(db, case_no))


# ---------------------------------------------------------------------------
# 联系 / 日程 / 停机 / 材料 / 保管
# ---------------------------------------------------------------------------

@router.post("/cases/{case_no}/contact")
def contact(case_no: str, body: ContactIn, db: Session = Depends(get_db),
            user: models.User = Depends(require_roles(*CS))):
    svc.log_contact(db, case_no, user, channel=body.channel, note=body.note,
                    next_contact_at=_aware(body.next_contact_at),
                    next_contact_note=body.next_contact_note)
    db.commit()
    return {"ok": True, "case": case_detail(db, svc.get_case(db, case_no))}


@router.post("/cases/{case_no}/schedule")
def schedule(case_no: str, body: ScheduleIn, db: Session = Depends(get_db),
             user: models.User = Depends(require_roles(*CS))):
    svc.update_schedule(db, case_no, user,
                        commitment_deadline=_aware(body.commitment_deadline),
                        commitment_note=body.commitment_note,
                        next_contact_at=_aware(body.next_contact_at),
                        next_contact_note=body.next_contact_note or "")
    db.commit()
    return {"ok": True}


@router.post("/cases/{case_no}/downtime")
def downtime(case_no: str, body: ActionIn, db: Session = Depends(get_db),
             user: models.User = Depends(require_roles(*CS, *WH))):
    svc.downtime(db, case_no, user, body.action)
    db.commit()
    return {"ok": True}


@router.post("/cases/{case_no}/materials")
def materials(case_no: str, body: MaterialsIn, db: Session = Depends(get_db),
              user: models.User = Depends(require_roles(*CS))):
    svc.set_materials(db, case_no, user, complete=body.complete, note=body.note)
    db.commit()
    return {"ok": True}


@router.post("/cases/{case_no}/custody")
def custody(case_no: str, body: CustodyIn, db: Session = Depends(get_db),
            user: models.User = Depends(require_roles(*CS, *WH))):
    svc.transfer_custody(db, case_no, user, party=body.party, name=body.name,
                         scope=body.scope, note=body.note)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# 工程补核 / 责任
# ---------------------------------------------------------------------------

@router.post("/cases/{case_no}/engineering-checks")
def add_check(case_no: str, body: EngCheckIn, db: Session = Depends(get_db),
              user: models.User = Depends(require_roles(*ENG, *CS))):
    chk = svc.add_engineering_check(db, case_no, user, kind=body.kind,
                                    title=body.title, description=body.description)
    db.commit()
    return {"ok": True, "id": chk.id}


@router.post("/engineering-checks/{check_id}/conclude")
def conclude_check(check_id: int, body: ConcludeCheckIn, db: Session = Depends(get_db),
                   user: models.User = Depends(require_roles(*ENG))):
    svc.conclude_engineering_check(db, check_id, user, result=body.result,
                                   conclusion=body.conclusion)
    db.commit()
    return {"ok": True}


@router.post("/cases/{case_no}/liability")
def liability(case_no: str, body: LiabilityIn, db: Session = Depends(get_db),
              user: models.User = Depends(require_roles(*ENG))):
    svc.decide_liability(db, case_no, user, liability=body.liability,
                        rationale=body.rationale)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# 押金 / 付款
# ---------------------------------------------------------------------------

@router.post("/cases/{case_no}/deposit/require")
def deposit_require(case_no: str, body: AmountIn, db: Session = Depends(get_db),
                    user: models.User = Depends(require_roles(*FIN))):
    svc.set_deposit_required(db, case_no, user, body.amount)
    db.commit()
    return {"ok": True}


@router.post("/cases/{case_no}/deposit/pay")
def deposit_pay(case_no: str, body: PayIn, db: Session = Depends(get_db),
                user: models.User = Depends(require_roles(*FIN))):
    svc.mark_deposit_paid(db, case_no, user, amount=body.amount, gateway_ref=body.gateway_ref)
    db.commit()
    return {"ok": True}


@router.post("/cases/{case_no}/deposit/refund-request")
def refund_request(case_no: str, db: Session = Depends(get_db),
                   user: models.User = Depends(require_roles(*FIN))):
    svc.request_deposit_refund(db, case_no, user)
    db.commit()
    return {"ok": True}


@router.post("/cases/{case_no}/deposit/refund-query")
def refund_query(case_no: str, db: Session = Depends(get_db),
                 user: models.User = Depends(require_roles(*FIN))):
    dep = svc.query_deposit_refund(db, case_no, user)
    db.commit()
    return {"ok": True, "deposit_status": dep.status}


@router.post("/cases/{case_no}/deposit/forfeit")
def forfeit(case_no: str, body: ReasonIn, db: Session = Depends(get_db),
            user: models.User = Depends(require_roles(*FIN))):
    svc.forfeit_deposit(db, case_no, user, body.reason)
    db.commit()
    return {"ok": True}


@router.post("/cases/{case_no}/payment-hold")
def payment_hold(case_no: str, body: HoldIn, db: Session = Depends(get_db),
                 user: models.User = Depends(require_roles(*CS, *FIN))):
    svc.set_payment_hold(db, case_no, user, held=body.held, reason=body.reason)
    db.commit()
    return {"ok": True}


@router.post("/cases/{case_no}/payment-resolve")
def payment_resolve(case_no: str, body: ResolutionIn, db: Session = Depends(get_db),
                    user: models.User = Depends(require_roles(*FIN))):
    svc.resolve_payment(db, case_no, user, body.resolution)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# 旧件 / 检测 / 维修
# ---------------------------------------------------------------------------

@router.post("/cases/{case_no}/old-part/send")
def old_send(case_no: str, body: TrackingIn, db: Session = Depends(get_db),
             user: models.User = Depends(require_roles(*CS, *WH))):
    svc.mark_old_part_sent(db, case_no, user, body.tracking_no)
    db.commit()
    return {"ok": True}


@router.post("/cases/{case_no}/old-part/receive")
def old_receive(case_no: str, body: TrackingIn, db: Session = Depends(get_db),
                user: models.User = Depends(require_roles(*WH))):
    svc.receive_old_part(db, case_no, user, body.tracking_no)
    db.commit()
    return {"ok": True}


@router.post("/cases/{case_no}/old-part/to-rework-stock")
def old_stock(case_no: str, db: Session = Depends(get_db),
              user: models.User = Depends(require_roles(*WH, *ENG))):
    svc.move_to_rework_stock(db, case_no, user)
    db.commit()
    return {"ok": True}


@router.post("/cases/{case_no}/old-part/scrap")
def old_scrap(case_no: str, body: ReasonIn, db: Session = Depends(get_db),
              user: models.User = Depends(require_roles(*WH, *ENG))):
    svc.scrap_old_part(db, case_no, user, body.note or body.reason)
    db.commit()
    return {"ok": True}


@router.post("/cases/{case_no}/old-part/return-customer")
def old_return(case_no: str, body: ReasonIn, db: Session = Depends(get_db),
               user: models.User = Depends(require_roles(*CS, *WH))):
    svc.return_old_part_to_customer(db, case_no, user, body.note or body.reason)
    db.commit()
    return {"ok": True}


@router.post("/cases/{case_no}/inspection/start")
def insp_start(case_no: str, db: Session = Depends(get_db),
               user: models.User = Depends(require_roles(*ENG, *WH))):
    svc.start_inspection(db, case_no, user)
    db.commit()
    return {"ok": True}


@router.post("/cases/{case_no}/inspection/conclude")
def insp_conclude(case_no: str, body: InspectionConcludeIn, db: Session = Depends(get_db),
                  user: models.User = Depends(require_roles(*ENG))):
    svc.conclude_inspection(db, case_no, user, result=body.result,
                            liability=body.liability, report=body.report)
    db.commit()
    return {"ok": True}


@router.post("/cases/{case_no}/repairs")
def add_repair(case_no: str, body: RepairIn, db: Session = Depends(get_db),
               user: models.User = Depends(require_roles(*ENG, *WH))):
    rec = svc.record_repair(
        db, case_no, user, repair_kind=body.repair_kind,
        actual_component_name=body.actual_component_name,
        actual_component_serial=body.actual_component_serial, quantity=body.quantity,
        old_component_disposition=body.old_component_disposition,
        whole_unit_whereabouts=body.whole_unit_whereabouts, note=body.note,
        final_disposition=body.final_disposition)
    db.commit()
    return {"ok": True, "id": rec.id}


@router.post("/cases/{case_no}/withdraw")
def withdraw(case_no: str, db: Session = Depends(get_db),
             user: models.User = Depends(require_roles(*CS))):
    svc.withdraw_case(db, case_no, user)
    return {"ok": True}


@router.post("/cases/{case_no}/exchange/auto-assign")
def exchange_auto_assign(case_no: str, body: ExchangeAssignIn, db: Session = Depends(get_db),
                         user: models.User = Depends(require_roles(*CS, *WH, "admin"))):
    plan = svc.auto_assign_exchange(db, case_no, user,
                                    supply_serial=body.supply_serial, cost=body.cost)
    return {"ok": True, "plan": plan_out(plan)}


@router.post("/cases/{case_no}/close")
def close(case_no: str, body: CloseIn, db: Session = Depends(get_db),
          user: models.User = Depends(require_roles(*CS, "admin"))):
    svc.close_case(db, case_no, user, note=body.note)
    return {"ok": True, "case": case_detail(db, svc.get_case(db, case_no))}


# ---------------------------------------------------------------------------
# 替换件寄出 / 签收
# ---------------------------------------------------------------------------

@router.post("/replacement-orders/{order_id}/ship")
def ship(order_id: int, body: ShipIn, db: Session = Depends(get_db),
         user: models.User = Depends(require_roles(*WH))):
    o = svc.ship_replacement(db, order_id, user, body.tracking_no)
    return {"ok": True, "shipment_status": o.shipment_status}


@router.post("/replacement-orders/{order_id}/sign")
def sign(order_id: int, body: SignIn, db: Session = Depends(get_db),
         user: models.User = Depends(require_roles(*CS, *WH))):
    o = svc.sign_replacement(db, order_id, user, signer=body.signer)
    return {"ok": True, "signoff_status": o.signoff_status}


# ---------------------------------------------------------------------------
# 备件 / 兼容表 / 指派
# ---------------------------------------------------------------------------

BATCHES = ["REAL", "R-DEMO", "FULL68", "SAFE", "CASE-EX"]


@router.get("/assignment/state")
def assignment_state(db: Session = Depends(get_db),
                     _: models.User = Depends(get_current_user)):
    out = []
    for b in BATCHES:
        demands = db.scalars(select(models.AssignDemand).where(
            models.AssignDemand.batch == b).order_by(models.AssignDemand.code)).all()
        prefix_batch = b
        units = db.scalars(select(models.SpareUnit).where(
            models.SpareUnit.batch == prefix_batch).order_by(models.SpareUnit.serial_no)).all()
        edges = db.scalars(select(models.CompatEdge).where(
            models.CompatEdge.batch == b).order_by(
            models.CompatEdge.demand_code, models.CompatEdge.supply_code)).all()
        out.append({
            "batch": b,
            "demands": [{"code": d.code, "approved": d.approved,
                         "fulfilled": d.fulfilled, "case_id": d.case_id,
                         "title": d.title} for d in demands],
            "units": [unit_out(u) for u in units],
            "edges": [{"demand_code": e.demand_code, "supply_code": e.supply_code,
                       "cost": e.cost} for e in edges],
        })
    return {"batches": out}


@router.get("/units")
def list_units(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.scalars(select(models.SpareUnit).order_by(models.SpareUnit.id)).all()
    return [unit_out(u) for u in rows]


@router.post("/units/restock")
def restock(body: RestockIn, db: Session = Depends(get_db),
            user: models.User = Depends(require_roles(*WH, "admin"))):
    u = svc.restock_unit(db, user, serial_no=body.serial_no, batch=body.batch,
                         model_code=body.model_code, name=body.name)
    return {"ok": True, "unit": unit_out(u)}


@router.post("/units/{serial_no}/safety")
def safety(serial_no: str, body: SafetyIn, db: Session = Depends(get_db),
           user: models.User = Depends(require_roles("safety", *ENG, "admin"))):
    u = svc.set_safety_qualification(db, serial_no, user, released=body.released,
                                     note=body.note)
    return {"ok": True, "unit": unit_out(u)}


@router.post("/compat-edges")
def add_edge(body: EdgeIn, db: Session = Depends(get_db),
             user: models.User = Depends(require_roles(*WH, "admin"))):
    e = svc.add_compat_edge(db, user, batch=body.batch, demand_code=body.demand_code,
                            supply_code=body.supply_code, cost=body.cost)
    return {"ok": True, "id": e.id}


@router.post("/assignment/{batch}/solve")
def solve(batch: str, db: Session = Depends(get_db),
          user: models.User = Depends(require_roles(*CS, *WH, "admin"))):
    if batch not in BATCHES:
        raise BusinessRuleError(f"未知指派批次 {batch}", code="bad_batch")
    plan = svc.solve_batch(db, batch, user)
    db.commit()
    return {"ok": True, "plan": plan_out(plan)}


@router.get("/plans")
def plans(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.scalars(select(models.AssignmentPlan).order_by(
        models.AssignmentPlan.id.desc()).limit(50)).all()
    return [plan_out(p) for p in rows]


@router.get("/plans/{plan_id}")
def get_plan(plan_id: int, db: Session = Depends(get_db),
             _: models.User = Depends(get_current_user)):
    p = db.get(models.AssignmentPlan, plan_id)
    if not p:
        from ..services.errors import NotFoundError
        raise NotFoundError("方案不存在")
    return plan_out(p)


@router.post("/plans/{plan_id}/approve")
def approve(plan_id: int, db: Session = Depends(get_db),
            user: models.User = Depends(require_roles(*WH, *CS, "admin"))):
    p = svc.approve_plan(db, plan_id, user)
    return {"ok": True, "plan": plan_out(p)}


# ---------------------------------------------------------------------------
# 脚本化演示：分配后安全资格撤回（真实执行 求解→撤回→原子批准被拒→重算）
# ---------------------------------------------------------------------------

@router.post("/demo/safety-withdrawal")
def demo_safety_withdrawal(db: Session = Depends(get_db),
                           user: models.User = Depends(require_roles(*CS, *ENG, "admin"))):
    steps: list[dict] = []

    # 重置 SAFE 批次到初始状态，保证演示可重复
    for code in ("SD-1", "SD-2"):
        d = db.scalar(select(models.AssignDemand).where(
            models.AssignDemand.batch == "SAFE", models.AssignDemand.code == code))
        if d:
            d.fulfilled = False
            d.fulfilled_at = None
    for sc in ("SS-1", "SS-2"):
        u = db.scalar(select(models.SpareUnit).where(models.SpareUnit.serial_no == sc))
        if u:
            u.status = "available"
            u.safety_released = True
            u.whole_exchange_blocked = False
    db.query(models.ReplacementOrder).filter(
        models.ReplacementOrder.demand_code.in_(("SD-1", "SD-2"))).delete(synchronize_session=False)
    db.query(models.AssignmentPlan).filter(models.AssignmentPlan.batch == "SAFE").delete()
    db.commit()

    plan = svc.solve_batch(db, "SAFE", user)
    db.commit()
    steps.append({"step": "solve", "ok": True,
                  "message": f"精确搜索得到候选方案 {plan.plan_no}："
                             + "，".join(f"{i['demand_code']}→{i['supply_code']}"
                                         f"(费{i['cost']})" for i in plan.items),
                  "plan": plan_out(plan)})

    svc.set_safety_qualification(db, "SS-1", user, released=False,
                                 note="演示：分配后安全资格被撤回（绝缘复检待确认）")
    steps.append({"step": "withdraw", "ok": True,
                  "message": "安全工程师撤回 SS-1 的放行资格；候选方案本身不占库存，"
                             "SS-1 仍显示为原候选但已不可批准"})

    stale_id = plan.id
    try:
        svc.approve_plan(db, stale_id, user)
        steps.append({"step": "approve_stale", "ok": True,
                      "message": "异常：旧方案竟然批准成功"})
    except BusinessRuleError as e:
        steps.append({"step": "approve_stale", "ok": False, "expected_rejection": True,
                      "code": e.code, "message": e.message, "details": e.details})

    stale_plan = db.get(models.AssignmentPlan, stale_id)
    steps.append({"step": "plan_state", "ok": stale_plan.status == "stale",
                  "message": f"旧方案状态={stale_plan.status}，未生成任何半份替换单",
                  "plan": plan_out(stale_plan)})

    new_plan = svc.solve_batch(db, "SAFE", user)
    db.commit()
    steps.append({"step": "resolve", "ok": True,
                  "message": "资格变化后重新精确搜索："
                             + ("，".join(f"{i['demand_code']}→{i['supply_code']}"
                                          for i in new_plan.items) or "无可满足需求"),
                  "plan": plan_out(new_plan)})
    return {"ok": True, "steps": steps}


@router.post("/demo/reset")
def demo_reset(db: Session = Depends(get_db),
               _: models.User = Depends(require_roles("admin"))):
    from ..seed_aftersales import reset_aftersales
    reset_aftersales(db)
    users = {u.username: u for u in db.scalars(select(models.User)).all()}
    seed_aftersales(db, users)
    db.commit()
    return {"ok": True, "message": "售后演示数据已重置"}
