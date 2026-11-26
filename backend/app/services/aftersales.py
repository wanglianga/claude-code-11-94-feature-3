"""售后客服业务服务。

覆盖：
- 虚构合同保修窗口（验收当地日历日 00:00 起，次年对应日 00:00 前，右端开区间）；
- 工程补核 / 责任结论（备注不能替代结论，在保不等于责任已证明）；
- 先寄替换件后收旧件（押金 + 已批准兼容备件）与先收旧件复检后换货（停机/保管/付款暂缓）；
- 寄出、签收、旧件回收、返修检测、押金退款五个互相独立的状态；
- 候选方案不占库存，批准出库时行锁原子复核，过期方案整案退回；
- 端子级维修留真实部件与去向，整机序列号不得重复换出；
- 实物与资金待办分别结清 + 材料/结论齐备才允许结案。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..assignment import Edge, solve_assignment
from . import audit as audit_svc
from .errors import BusinessRuleError, NotFoundError

CST = timezone(timedelta(hours=8))  # 虚构合同按验收当地（北京时间）日历日计算


# ---------------------------------------------------------------------------
# 保修时间窗
# ---------------------------------------------------------------------------

def warranty_window(accepted_at: datetime) -> tuple[datetime, datetime]:
    """合同保修：验收当日 00:00 起，至次年同月同日 00:00（不含）。"""
    local = accepted_at.astimezone(CST)
    start = datetime(local.year, local.month, local.day, tzinfo=CST)
    end = datetime(local.year + 1, local.month, local.day, tzinfo=CST)
    return start, end


def warranty_view(case: models.AftersalesCase, at: datetime | None = None) -> dict:
    at = at or models.utcnow()
    start, end = case.warranty_start, case.warranty_end
    appealed_in_window = start <= case.appealed_at < end
    return {
        "accepted_at": case.accepted_at.isoformat(),
        "warranty_start": start.isoformat(),
        "warranty_end": end.isoformat(),
        "appealed_at": case.appealed_at.isoformat(),
        "appealed_in_window": appealed_in_window,
        "checked_at": at.isoformat(),
        "currently_in_window": start <= at < end,
        "rule": "保修区间为 [验收当日 00:00, 次年对应日 00:00)；次年对应日 00:00 整已不在保。",
        "liability_notice": "在保仅表示合同时间窗成立，不等于检测已证明责任；"
                            "运输压痕、安装温度回执缺失须由工程人员补核出结论。",
    }


# ---------------------------------------------------------------------------
# 通用读取
# ---------------------------------------------------------------------------

def get_case(db: Session, case_no: str) -> models.AftersalesCase:
    case = db.scalar(select(models.AftersalesCase).where(models.AftersalesCase.case_no == case_no))
    if not case:
        raise NotFoundError(f"售后案件 {case_no} 不存在")
    return case


def terminal_repaired_serials(db: Session) -> set[str]:
    """所有做过“仅端子维修”的整机序列号——永久禁止作为整机重复换出。"""
    rows = db.scalars(select(models.RepairRecord.old_whole_serial).where(
        models.RepairRecord.repair_kind == "terminal_only")).all()
    return set(rows)


def serial_blocked_reason(db: Session, serial_no: str,
                          terminal_serials: set[str] | None = None) -> str | None:
    """返回该序列号被禁止整机指派/换出的原因；未锁定返回 None。"""
    unit = db.scalar(select(models.SpareUnit).where(models.SpareUnit.serial_no == serial_no))
    if unit is not None and unit.whole_exchange_blocked:
        return f"整机序列号 {serial_no} 已被标记禁止整机换出（端子维修件）"
    if terminal_serials is None:
        terminal_serials = terminal_repaired_serials(db)
    if serial_no in terminal_serials:
        return f"整机序列号 {serial_no} 有端子级维修记录，只记录真实部件维修，不得作为整机重复换出"
    return None


def _add_event(db: Session, case: models.AftersalesCase, scope: str,
               to_party: str, note: str, user: models.User,
               from_party: str = "") -> None:
    db.add(models.CustodyEvent(
        case_id=case.id, scope=scope, from_party=from_party,
        to_party=to_party, note=note, actor_id=user.id,
    ))


# ---------------------------------------------------------------------------
# 联系 / 承诺 / 停机 / 材料 / 保管
# ---------------------------------------------------------------------------

def log_contact(db: Session, case_no: str, user: models.User, *,
                channel: str, note: str,
                next_contact_at: datetime | None = None,
                next_contact_note: str = "") -> models.CaseContact:
    case = get_case(db, case_no)
    rec = models.CaseContact(case_id=case.id, channel=channel, note=note, actor_id=user.id)
    db.add(rec)
    if next_contact_at is not None:
        case.next_contact_at = next_contact_at
        case.next_contact_note = next_contact_note or note[:120]
    audit_svc.log(db, user.id, "as_contact_logged", "aftersales_case", case.case_no,
                  {"channel": channel, "next_contact_at": next_contact_at.isoformat() if next_contact_at else None})
    db.flush()
    return rec


def update_schedule(db: Session, case_no: str, user: models.User, *,
                    commitment_deadline: datetime | None = None,
                    commitment_note: str | None = None,
                    next_contact_at: datetime | None = None,
                    next_contact_note: str | None = None) -> models.AftersalesCase:
    case = get_case(db, case_no)
    if commitment_deadline is not None:
        case.commitment_deadline = commitment_deadline
    if commitment_note is not None:
        case.commitment_note = commitment_note
    if next_contact_at is not None:
        case.next_contact_at = next_contact_at
    if next_contact_note is not None:
        case.next_contact_note = next_contact_note
    audit_svc.log(db, user.id, "as_schedule_updated", "aftersales_case", case.case_no)
    return case


def downtime(db: Session, case_no: str, user: models.User, action: str) -> models.AftersalesCase:
    case = get_case(db, case_no)
    if action == "start":
        if case.downtime_started_at and not case.downtime_ended_at:
            raise BusinessRuleError("停机时段已经开始且尚未结束", code="downtime_already_open")
        case.downtime_started_at = models.utcnow()
        case.downtime_ended_at = None
    elif action == "end":
        if not case.downtime_started_at:
            raise BusinessRuleError("尚未登记停机开始时间", code="downtime_not_started")
        if case.downtime_ended_at:
            raise BusinessRuleError("停机时段已经结束", code="downtime_already_closed")
        case.downtime_ended_at = models.utcnow()
    else:
        raise BusinessRuleError("action 只能是 start|end", code="bad_action")
    audit_svc.log(db, user.id, f"as_downtime_{action}", "aftersales_case", case.case_no)
    return case


def set_materials(db: Session, case_no: str, user: models.User, *,
                  complete: bool, note: str = "") -> models.AftersalesCase:
    case = get_case(db, case_no)
    case.materials_complete = complete
    if note:
        case.materials_note = note
    audit_svc.log(db, user.id, "as_materials_updated", "aftersales_case", case.case_no,
                  {"complete": complete})
    return case


def transfer_custody(db: Session, case_no: str, user: models.User, *,
                     party: str, name: str, scope: str = "old_part",
                     note: str = "") -> models.AftersalesCase:
    case = get_case(db, case_no)
    old_name = case.custodian_name
    if scope == "old_part":
        case.custodian_party = party
        case.custodian_name = name
    _add_event(db, case, scope, name or party, note, user, from_party=old_name)
    audit_svc.log(db, user.id, "as_custody_transfer", "aftersales_case", case.case_no,
                  {"scope": scope, "to": name or party})
    return case


# ---------------------------------------------------------------------------
# 工程补核与责任结论
# ---------------------------------------------------------------------------

def add_engineering_check(db: Session, case_no: str, user: models.User, *,
                          kind: str, title: str, description: str = "") -> models.EngineeringCheck:
    case = get_case(db, case_no)
    chk = models.EngineeringCheck(case_id=case.id, kind=kind, title=title,
                                  description=description)
    db.add(chk)
    audit_svc.log(db, user.id, "as_eng_check_added", "engineering_check", case.case_no,
                  {"kind": kind, "title": title})
    db.flush()
    return chk


def conclude_engineering_check(db: Session, check_id: int, user: models.User, *,
                               result: str, conclusion: str) -> models.EngineeringCheck:
    if result not in ("confirmed", "ruled_out"):
        raise BusinessRuleError("补核结果只能是 confirmed|ruled_out", code="bad_result")
    if not conclusion.strip():
        # 核心规则：备注不能替代结论
        raise BusinessRuleError("必须填写工程补核结论；普通备注不能替代结论",
                                code="conclusion_required")
    chk = db.get(models.EngineeringCheck, check_id)
    if not chk:
        raise NotFoundError("工程补核项不存在")
    chk.status = "concluded"
    chk.result = result
    chk.conclusion = conclusion.strip()
    chk.engineer_id = user.id
    chk.concluded_at = models.utcnow()
    case = db.get(models.AftersalesCase, chk.case_id)
    audit_svc.log(db, user.id, "as_eng_check_concluded", "engineering_check", str(check_id),
                  {"case": case.case_no if case else None, "result": result})
    db.flush()
    return chk


def decide_liability(db: Session, case_no: str, user: models.User, *,
                    liability: str, rationale: str) -> models.AftersalesCase:
    """出具责任结论。必须有已结论的检测/工程证据；仅凭“在保”或备注一律拒绝。"""
    if liability not in ("supplier", "transport", "customer", "shared"):
        raise BusinessRuleError("liability 必须是 supplier|transport|customer|shared",
                                code="bad_liability")
    if not rationale.strip():
        raise BusinessRuleError("责任结论必须写明依据", code="rationale_required")
    case = get_case(db, case_no)

    insp = db.scalar(select(models.ReworkInspection).where(
        models.ReworkInspection.case_id == case.id))
    concluded_checks = db.scalars(select(models.EngineeringCheck).where(
        models.EngineeringCheck.case_id == case.id,
        models.EngineeringCheck.status == "concluded")).all()
    has_inspection_proof = bool(insp and insp.status == "concluded"
                                and insp.liability != "undetermined")
    if not has_inspection_proof and not concluded_checks:
        raise BusinessRuleError(
            "责任结论必须以已完成的返修检测结论或工程补核结论为证据；"
            "在保不等于责任成立（保修时间窗有效不能证明责任），备注也不能替代结论。",
            code="liability_evidence_required")

    case.liability_status = liability
    case.liability_basis = rationale.strip()
    case.liability_by_id = user.id
    case.liability_at = models.utcnow()
    audit_svc.log(db, user.id, "as_liability_decided", "aftersales_case", case.case_no,
                  {"liability": liability})
    return case


# ---------------------------------------------------------------------------
# 押金 / 付款暂缓
# ---------------------------------------------------------------------------

def _get_or_create_deposit(db: Session, case: models.AftersalesCase) -> models.Deposit:
    dep = db.scalar(select(models.Deposit).where(models.Deposit.case_id == case.id))
    if not dep:
        dep = models.Deposit(case_id=case.id, status="pending")
        db.add(dep)
        db.flush()
    return dep


def set_deposit_required(db: Session, case_no: str, user: models.User, amount: int) -> models.Deposit:
    case = get_case(db, case_no)
    if amount <= 0:
        raise BusinessRuleError("押金金额必须为正整数", code="bad_amount")
    dep = _get_or_create_deposit(db, case)
    if dep.status in ("paid", "refund_unknown", "refunded"):
        raise BusinessRuleError("押金已收取或已进入退款流程，不能直接改金额", code="deposit_locked")
    dep.amount = amount
    dep.status = "pending"
    audit_svc.log(db, user.id, "as_deposit_required", "deposit", case.case_no, {"amount": amount})
    db.flush()
    return dep


def mark_deposit_paid(db: Session, case_no: str, user: models.User,
                      amount: int | None = None, gateway_ref: str = "PAY-COUNTER") -> models.Deposit:
    case = get_case(db, case_no)
    dep = _get_or_create_deposit(db, case)
    if dep.status == "refunded":
        raise BusinessRuleError("押金已退还，不能重复收取", code="deposit_already_refunded")
    if amount is not None:
        dep.amount = amount
    if dep.amount <= 0:
        raise BusinessRuleError("请先登记押金金额", code="deposit_amount_missing")
    dep.status = "paid"
    dep.paid_at = models.utcnow()
    dep.gateway_ref = gateway_ref
    audit_svc.log(db, user.id, "as_deposit_paid", "deposit", case.case_no,
                  {"amount": dep.amount, "ref": gateway_ref})
    db.flush()
    return dep


def request_deposit_refund(db: Session, case_no: str, user: models.User) -> models.Deposit:
    """发起退款。演示通道不返回明确结果 → refund_unknown（未知不是已退）。"""
    case = get_case(db, case_no)
    dep = _get_or_create_deposit(db, case)
    if dep.status not in ("paid", "refund_pending", "refund_unknown"):
        raise BusinessRuleError(f"当前押金状态 {dep.status} 不能发起退款", code="refund_not_allowed")
    now = models.utcnow()
    dep.status = "refund_unknown"
    dep.refund_requested_at = dep.refund_requested_at or now
    dep.unknown_since = now
    dep.gateway_ref = dep.gateway_ref or f"RF-{case.case_no}"
    audit_svc.log(db, user.id, "as_refund_requested_unknown", "deposit", case.case_no,
                  {"gateway_ref": dep.gateway_ref,
                   "message": "支付通道未返回明确结果，登记为退款未知，禁止按已退入账"})
    db.flush()
    return dep


def query_deposit_refund(db: Session, case_no: str, user: models.User) -> models.Deposit:
    """向通道查询退款结果。模拟对账：查询一次后确认退款成功。"""
    case = get_case(db, case_no)
    dep = _get_or_create_deposit(db, case)
    if dep.status not in ("refund_unknown", "refund_pending"):
        raise BusinessRuleError(f"当前押金状态 {dep.status} 无需查询退款", code="query_not_allowed")
    dep.query_count += 1
    # 模拟通道对账：有过一次查询即拿到成功回执
    dep.status = "refunded"
    dep.refunded_at = models.utcnow()
    audit_svc.log(db, user.id, "as_refund_confirmed", "deposit", case.case_no,
                  {"query_count": dep.query_count})
    db.flush()
    return dep


def forfeit_deposit(db: Session, case_no: str, user: models.User, reason: str) -> models.Deposit:
    """押金扣除/没收，也是一种资金结清。"""
    case = get_case(db, case_no)
    dep = _get_or_create_deposit(db, case)
    if dep.status not in ("paid", "refund_unknown", "refund_pending"):
        raise BusinessRuleError(f"当前押金状态 {dep.status} 不能扣除", code="forfeit_not_allowed")
    dep.status = "forfeited"
    audit_svc.log(db, user.id, "as_deposit_forfeited", "deposit", case.case_no, {"reason": reason})
    db.flush()
    return dep


def set_payment_hold(db: Session, case_no: str, user: models.User, *,
                     held: bool, reason: str = "") -> models.AftersalesCase:
    case = get_case(db, case_no)
    case.payment_held = held
    if held:
        case.payment_hold_reason = reason or "复检结论出具前暂缓付款"
        case.payment_resolved = False
    audit_svc.log(db, user.id, "as_payment_hold", "aftersales_case", case.case_no, {"held": held})
    return case


def resolve_payment(db: Session, case_no: str, user: models.User, resolution: str) -> models.AftersalesCase:
    if resolution not in ("released", "deducted", "waived"):
        raise BusinessRuleError("resolution 必须是 released|deducted|waived", code="bad_resolution")
    case = get_case(db, case_no)
    if not case.payment_held:
        raise BusinessRuleError("本案没有暂缓中的付款", code="no_payment_hold")
    case.payment_resolved = True
    case.payment_resolution = resolution
    audit_svc.log(db, user.id, "as_payment_resolved", "aftersales_case", case.case_no,
                  {"resolution": resolution})
    return case


# ---------------------------------------------------------------------------
# 旧件回收（③）与返修检测（④）
# ---------------------------------------------------------------------------

def _get_return(db: Session, case: models.AftersalesCase) -> models.OldPartReturn:
    ret = db.scalar(select(models.OldPartReturn).where(models.OldPartReturn.case_id == case.id))
    if not ret:
        raise BusinessRuleError("旧件回收单尚未建立", code="return_not_found")
    return ret


def mark_old_part_sent(db: Session, case_no: str, user: models.User,
                       tracking_no: str = "") -> models.OldPartReturn:
    case = get_case(db, case_no)
    ret = _get_return(db, case)
    if ret.status == "received":
        raise BusinessRuleError("旧件已实收，不能再登记寄出", code="already_received")
    ret.status = "in_transit"
    ret.sent_at = models.utcnow()
    if tracking_no:
        ret.tracking_no = tracking_no
    _add_event(db, case, "old_part", "物流在途", f"客户交寄旧件 {ret.whole_serial}", user,
               from_party=case.custodian_name)
    audit_svc.log(db, user.id, "as_oldpart_sent", "old_part_return", case.case_no)
    db.flush()
    return ret


def receive_old_part(db: Session, case_no: str, user: models.User,
                     tracking_no: str = "") -> models.OldPartReturn:
    """仓库实际签收旧件。只有这一步之后旧件才物理到手。"""
    case = get_case(db, case_no)
    ret = _get_return(db, case)
    if ret.status == "received":
        raise BusinessRuleError("旧件已实收，请勿重复签收", code="already_received")
    now = models.utcnow()
    ret.status = "received"
    ret.received_at = now
    ret.received_by_id = user.id
    if tracking_no:
        ret.tracking_no = tracking_no
    case.custodian_party = "warehouse"
    case.custodian_name = "售后仓（旧件待检区）"
    _add_event(db, case, "old_part", case.custodian_name,
               f"仓库实收旧件 {ret.whole_serial}；未实收前不得成为返修库存", user,
               from_party="客户/物流")
    audit_svc.log(db, user.id, "as_oldpart_received", "old_part_return", case.case_no,
                  {"whole_serial": ret.whole_serial,
                   "overdue": bool(ret.due_at and now > ret.due_at)})
    db.flush()
    return ret


def move_to_rework_stock(db: Session, case_no: str, user: models.User) -> models.OldPartReturn:
    """旧件成为返修库存：硬门禁——必须已实际签收。"""
    case = get_case(db, case_no)
    ret = _get_return(db, case)
    if ret.status != "received":
        raise BusinessRuleError(
            "旧件尚未实际回收签收，不能成为返修库存；在途/客户保管中的实物不得计入返修库存。",
            code="old_part_not_received")
    ret.disposition = "rework_stock"
    ret.disposition_note = "实物已入返修库存台账"
    case.custodian_party = "lab"
    case.custodian_name = "返修检测区"
    _add_event(db, case, "old_part", case.custodian_name, "旧件转入返修库存", user,
               from_party="售后仓（旧件待检区）")
    audit_svc.log(db, user.id, "as_rework_stock_in", "old_part_return", case.case_no)
    db.flush()
    return ret


def start_inspection(db: Session, case_no: str, user: models.User) -> models.ReworkInspection:
    case = get_case(db, case_no)
    ret = _get_return(db, case)
    if ret.status != "received":
        raise BusinessRuleError("旧件未实收，不能开始返修检测", code="old_part_not_received")
    insp = db.scalar(select(models.ReworkInspection).where(
        models.ReworkInspection.case_id == case.id))
    if not insp:
        insp = models.ReworkInspection(case_id=case.id)
        db.add(insp)
    if insp.status == "concluded":
        raise BusinessRuleError("返修检测已结论", code="inspection_concluded")
    insp.status = "in_progress"
    insp.started_at = insp.started_at or models.utcnow()
    insp.inspector_id = user.id
    audit_svc.log(db, user.id, "as_inspection_started", "rework_inspection", case.case_no)
    db.flush()
    return insp


def conclude_inspection(db: Session, case_no: str, user: models.User, *,
                        result: str, liability: str, report: str) -> models.ReworkInspection:
    if result not in ("terminal_repairable", "repairable", "no_fault",
                      "fault_confirmed", "scrap"):
        raise BusinessRuleError("检测结果取值非法", code="bad_result")
    if liability not in ("undetermined", "supplier", "transport", "customer", "shared"):
        raise BusinessRuleError("责任取值非法", code="bad_liability")
    if not report.strip():
        raise BusinessRuleError("必须填写检测报告/结论，备注不能替代检测结论",
                                code="report_required")
    case = get_case(db, case_no)
    ret = _get_return(db, case)
    if ret.status != "received":
        raise BusinessRuleError("旧件未实收，检测结论无效", code="old_part_not_received")
    insp = db.scalar(select(models.ReworkInspection).where(
        models.ReworkInspection.case_id == case.id))
    if not insp or insp.status != "in_progress":
        raise BusinessRuleError("请先开始返修检测再录入结论", code="inspection_not_started")
    insp.status = "concluded"
    insp.result = result
    insp.liability = liability
    insp.report = report.strip()
    insp.inspector_id = user.id
    insp.concluded_at = models.utcnow()

    # 检测已明确责任时，可直接形成责任结论（检测就是证据）
    if liability != "undetermined":
        case.liability_status = liability
        case.liability_basis = f"返修检测结论（{result}）：{report.strip()}"
        case.liability_by_id = user.id
        case.liability_at = insp.concluded_at
    audit_svc.log(db, user.id, "as_inspection_concluded", "rework_inspection", case.case_no,
                  {"result": result, "liability": liability})
    db.flush()
    return insp


def record_repair(db: Session, case_no: str, user: models.User, *,
                  repair_kind: str, actual_component_name: str,
                  actual_component_serial: str = "", quantity: int = 1,
                  old_component_disposition: str = "",
                  whole_unit_whereabouts: str = "", note: str = "",
                  final_disposition: str = "terminal_repair") -> models.RepairRecord:
    """记录真实维修。只修端子时必须写真实部件与整机/旧件去向，并锁死整机再次换出。"""
    if repair_kind not in ("terminal_only", "component_replace", "whole_replace"):
        raise BusinessRuleError("repair_kind 非法", code="bad_repair_kind")
    if not actual_component_name.strip():
        raise BusinessRuleError("必须记录实际更换/修复的真实部件名称", code="component_required")
    if not whole_unit_whereabouts.strip():
        raise BusinessRuleError("必须记录整机/旧件的实际去向", code="whereabouts_required")
    if quantity <= 0:
        raise BusinessRuleError("部件数量必须为正", code="bad_quantity")
    case = get_case(db, case_no)
    ret = _get_return(db, case)
    if ret.status != "received":
        raise BusinessRuleError("旧件未实收，不能登记实际维修", code="old_part_not_received")

    rec = models.RepairRecord(
        case_id=case.id, old_whole_serial=ret.whole_serial, repair_kind=repair_kind,
        actual_component_name=actual_component_name.strip(),
        actual_component_serial=actual_component_serial.strip(),
        quantity=quantity, old_component_disposition=old_component_disposition.strip(),
        whole_unit_whereabouts=whole_unit_whereabouts.strip(), note=note,
        technician_id=user.id)
    db.add(rec)

    # 旧件处置与整机去向同步到回收单
    ret.disposition = final_disposition
    ret.disposition_note = whole_unit_whereabouts.strip()

    # 核心防伪换：仅端子维修的整机序列号永久标记“禁止再次整机换出”，
    # 若库存中存在同序列号实物（如返修件），同步打标。
    unit = db.scalar(select(models.SpareUnit).where(
        models.SpareUnit.serial_no == ret.whole_serial))
    if repair_kind == "terminal_only":
        if unit is not None:
            unit.whole_exchange_blocked = True
        audit_svc.log(db, user.id, "as_terminal_repair_recorded", "repair_record", case.case_no,
                      {"component": actual_component_name,
                       "guard": f"整机序列号 {ret.whole_serial} 已禁止重复换出"})
    else:
        audit_svc.log(db, user.id, "as_repair_recorded", "repair_record", case.case_no,
                      {"kind": repair_kind})
    if unit is not None and final_disposition == "returned_customer":
        unit.status = "consumed"
    db.flush()
    return rec


def scrap_old_part(db: Session, case_no: str, user: models.User, note: str) -> models.OldPartReturn:
    case = get_case(db, case_no)
    ret = _get_return(db, case)
    if ret.status != "received":
        raise BusinessRuleError("旧件未实收，不能报废", code="old_part_not_received")
    ret.disposition = "scrapped"
    ret.disposition_note = note or "实物报废拆解"
    audit_svc.log(db, user.id, "as_oldpart_scrapped", "old_part_return", case.case_no)
    return ret


def return_old_part_to_customer(db: Session, case_no: str, user: models.User,
                                note: str) -> models.OldPartReturn:
    case = get_case(db, case_no)
    ret = _get_return(db, case)
    if ret.status != "received":
        raise BusinessRuleError("旧件未实收，不能原物退回", code="old_part_not_received")
    ret.disposition = "returned_customer"
    ret.disposition_note = note or "无故障/客户责任，原整机退回客户"
    case.custodian_party = "customer"
    case.custodian_name = "客户（旧件已退回）"
    _add_event(db, case, "old_part", case.custodian_name, ret.disposition_note, user,
               from_party="售后/检测区")
    audit_svc.log(db, user.id, "as_oldpart_returned_customer", "old_part_return", case.case_no)
    return ret


# ---------------------------------------------------------------------------
# 指派：从数据库构造当前输入、生成候选方案、原子批准
# ---------------------------------------------------------------------------

def _current_assignment_inputs(db: Session, batch: str) -> tuple[list[str], list[str], list[Edge]]:
    demands = db.scalars(select(models.AssignDemand).where(
        models.AssignDemand.batch == batch,
        models.AssignDemand.approved.is_(True),
        models.AssignDemand.fulfilled.is_(False),
    ).order_by(models.AssignDemand.code)).all()
    req_codes = [d.code for d in demands]

    # 备件资格按“兼容表引用到的序列号”逐件核对（换货批次可引用任意已登记实物）
    edge_rows = db.scalars(select(models.CompatEdge).where(
        models.CompatEdge.batch == batch)).all()
    referenced = sorted({e.supply_code for e in edge_rows})
    if referenced:
        units = db.scalars(select(models.SpareUnit).where(
            models.SpareUnit.serial_no.in_(referenced),
            models.SpareUnit.status == "available",
            models.SpareUnit.safety_released.is_(True),
            models.SpareUnit.whole_exchange_blocked.is_(False),
        ).order_by(models.SpareUnit.serial_no)).all()
    else:
        units = []
    supply_codes = [u.serial_no for u in units]
    # 维修记录维度的永久禁换（即使库存行标记缺失也拦截）
    blocked_serials = terminal_repaired_serials(db)
    supply_codes = [s for s in supply_codes if s not in blocked_serials]
    eligible = set(supply_codes)

    active_req_codes = set(req_codes)
    edges = [Edge(e.demand_code, e.supply_code, e.cost)
             for e in edge_rows
             if e.demand_code in active_req_codes and e.supply_code in eligible]
    return req_codes, supply_codes, edges


def create_exchange_demand(db: Session, case_no: str, user: models.User, *,
                           supply_serial: str, cost: int = 1) -> models.AssignDemand:
    """先检路径复检决定换货后，追加批准一条案件换货需求并指定兼容备件。"""
    case = get_case(db, case_no)
    insp = db.scalar(select(models.ReworkInspection).where(
        models.ReworkInspection.case_id == case.id))
    if not insp or insp.status != "concluded":
        raise BusinessRuleError("复检尚未结论，不能决定换货", code="inspection_not_concluded")
    unit = db.scalar(select(models.SpareUnit).where(models.SpareUnit.serial_no == supply_serial))
    if not unit:
        raise NotFoundError(f"备件 {supply_serial} 不存在，请先补库/登记实物")
    if unit.whole_exchange_blocked:
        raise BusinessRuleError(f"序列号 {supply_serial} 已被禁止作为整机换出",
                                code="serial_exchange_blocked")

    code = f"D-{case.case_no}"
    demand = db.scalar(select(models.AssignDemand).where(
        models.AssignDemand.batch == "CASE-EX", models.AssignDemand.code == code))
    if not demand:
        demand = models.AssignDemand(batch="CASE-EX", code=code, case_id=case.id,
                                    title=f"{case.customer_code} 复检后换货需求", approved=True)
        db.add(demand)
        db.flush()
    else:
        demand.approved = True
        demand.case_id = case.id
    edge = db.scalar(select(models.CompatEdge).where(
        models.CompatEdge.batch == "CASE-EX",
        models.CompatEdge.demand_code == code,
        models.CompatEdge.supply_code == supply_serial))
    if edge:
        edge.cost = cost
    else:
        db.add(models.CompatEdge(batch="CASE-EX", demand_code=code,
                                 supply_code=supply_serial, cost=cost))
    audit_svc.log(db, user.id, "as_exchange_demand_created", "assign_demand", code,
                  {"case": case.case_no, "supply": supply_serial})
    db.flush()
    return demand


def auto_assign_exchange(db: Session, case_no: str, user: models.User, *,
                         supply_serial: str, cost: int = 1) -> models.AssignmentPlan:
    """生成换货需求 → 精确搜索 → 原子批准，一步实际办结指派出库。"""
    create_exchange_demand(db, case_no, user, supply_serial=supply_serial, cost=cost)
    plan = solve_batch(db, "CASE-EX", user)
    db.flush()
    if plan.fulfilled_count < 1:
        raise BusinessRuleError("精确搜索未能满足该换货需求（备件可能已被占用或资格撤回）",
                                code="assignment_unfulfillable",
                                details={"stats": plan.stats})
    return approve_plan(db, plan.id, user)


def solve_batch(db: Session, batch: str, user: models.User | None = None,
                *, persist: bool = True) -> models.AssignmentPlan | dict:
    req_codes, supply_codes, edges = _current_assignment_inputs(db, batch)
    complete_space = None
    if batch == "FULL68":
        import math
        complete_space = math.perm(len(supply_codes), len(req_codes)) if req_codes else None
    result = solve_assignment(req_codes, supply_codes, edges,
                              batch=batch, complete_space=complete_space)
    if not persist:
        return result.to_dict()

    plan = models.AssignmentPlan(
        plan_no="", batch=batch, status="candidate",
        fulfilled_count=result.fulfilled_count, total_cost=result.total_cost,
        items=[{"demand_code": a["req_code"],
                "supply_code": a["supply_code"], "cost": a["cost"]}
               for a in result.assignments],
        unmet=result.unmet, stats=result.to_dict(),
        created_by_id=user.id if user else None)
    db.add(plan)
    db.flush()
    plan.plan_no = f"PL-{plan.id:04d}"
    audit_svc.log(db, user.id if user else None, "as_plan_solved", "assignment_plan", plan.plan_no,
                  {"batch": batch, "count": result.fulfilled_count,
                   "cost": result.total_cost,
                   "branches": result.branches_expanded,
                   "elapsed_ms": result.elapsed_ms})
    db.flush()
    return plan


def approve_plan(db: Session, plan_id: int, user: models.User) -> models.AssignmentPlan:
    """原子批准出库：行锁锁定全部需求/备件/兼容边后逐项复核。

    任一条件变化 → 整案标记 stale 并提交该状态，不创建任何替换单、不改任何库存。
    全部通过 → 一次性履行需求、占用备件、生成替换件单（待寄出状态）。
    """
    plan = db.get(models.AssignmentPlan, plan_id)
    if not plan:
        raise NotFoundError("指派方案不存在")
    if plan.status != "candidate":
        raise BusinessRuleError(f"方案 {plan.plan_no} 当前状态 {plan.status}，不能批准",
                                code="plan_not_candidate")
    items = list(plan.items or [])
    if not items:
        raise BusinessRuleError("空方案（无任何可满足需求）不能批准", code="empty_plan")

    demand_codes = sorted({i["demand_code"] for i in items})
    supply_codes = sorted({i["supply_code"] for i in items})
    if len(demand_codes) != len(items) or len(supply_codes) != len(items):
        raise BusinessRuleError("方案中存在重复需求或重复备件，拒绝执行",
                                code="duplicate_assignment")

    # 稳定顺序加锁，避免并发事务交叉死锁
    demands = db.scalars(select(models.AssignDemand).where(
        models.AssignDemand.batch == plan.batch,
        models.AssignDemand.code.in_(demand_codes),
    ).order_by(models.AssignDemand.code).with_for_update()).all()
    demand_map = {d.code: d for d in demands}

    units = db.scalars(select(models.SpareUnit).where(
        models.SpareUnit.serial_no.in_(supply_codes),
    ).order_by(models.SpareUnit.serial_no).with_for_update()).all()
    unit_map = {u.serial_no: u for u in units}

    edge_rows = db.scalars(select(models.CompatEdge).where(
        models.CompatEdge.batch == plan.batch,
        models.CompatEdge.demand_code.in_(demand_codes),
        models.CompatEdge.supply_code.in_(supply_codes),
    ).with_for_update()).all()
    edge_map = {(e.demand_code, e.supply_code): e for e in edge_rows}
    terminal_serials = terminal_repaired_serials(db)

    stale_reasons: list[str] = []
    precondition_errors: list[str] = []
    for item in items:
        dc, sc, cost = item["demand_code"], item["supply_code"], item.get("cost", 0)
        d = demand_map.get(dc)
        if d is None:
            stale_reasons.append(f"需求 {dc} 已不存在")
            continue
        if not d.approved:
            stale_reasons.append(f"需求 {dc} 批准已被撤回")
        if d.fulfilled:
            stale_reasons.append(f"需求 {dc} 已被其他方案履行")
        u = unit_map.get(sc)
        if u is None:
            stale_reasons.append(f"备件 {sc} 实物库存记录不存在")
            continue
        if u.status != "available":
            stale_reasons.append(f"备件 {sc} 当前状态为 {u.status}，已不再可用")
        if not u.safety_released:
            stale_reasons.append(f"备件 {sc} 的安全/放行资格已被撤回")
        if u.whole_exchange_blocked or sc in terminal_serials:
            stale_reasons.append(
                f"整机序列号 {sc} 为端子维修件/已锁死，禁止作为整机重复换出")
        e = edge_map.get((dc, sc))
        if e is None:
            stale_reasons.append(f"需求 {dc} 与备件 {sc} 的兼容关系已被删除/变化")
        elif int(e.cost) != int(cost):
            stale_reasons.append(f"{dc}→{sc} 的调配费用已由 {cost} 变为 {e.cost}")
        if d.case_id:
            case = db.get(models.AftersalesCase, d.case_id)
            if case is None:
                stale_reasons.append(f"需求 {dc} 关联案件不存在")
            elif case.status != "open" or case.closed:
                stale_reasons.append(f"需求 {dc} 关联案件 {case.case_no} 已结案/撤案")
            elif case.path == "advance_replace":
                dep = db.scalar(select(models.Deposit).where(models.Deposit.case_id == case.id))
                if not dep or dep.status != "paid":
                    # 可补正：押金收讫后同一方案仍可批准，因此不把方案置 stale
                    precondition_errors.append(
                        f"案件 {case.case_no} 尚未收讫押金，先换路径不能出库（收押金后可重新批准本方案）")

    if stale_reasons:
        # 旧方案退回：只持久化 stale 状态，不执行半份指派
        plan.status = "stale"
        plan.stale_reasons = stale_reasons
        audit_svc.log(db, user.id, "as_plan_rejected_stale", "assignment_plan", plan.plan_no,
                      {"reasons": stale_reasons})
        db.commit()
        raise BusinessRuleError(
            "批准时原子复核未通过，旧方案已退回（未执行任何半份指派）：" + "；".join(stale_reasons),
            code="assignment_stale", details={"reasons": stale_reasons})

    if precondition_errors:
        # 未做任何写入，会话关闭即回滚；方案保留 candidate，补正后可再次批准
        raise BusinessRuleError(
            "出库前置条件未满足：" + "；".join(precondition_errors),
            code="precondition_failed", details={"errors": precondition_errors})

    now = models.utcnow()
    created_orders: list[models.ReplacementOrder] = []
    for item in items:
        dc, sc, cost = item["demand_code"], item["supply_code"], item.get("cost", 0)
        d = demand_map[dc]
        u = unit_map[sc]
        d.fulfilled = True
        d.fulfilled_at = now
        u.status = "allocated"  # 批准出库：候选从此转为实际占用
        order = models.ReplacementOrder(
            case_id=d.case_id, plan_id=plan.id, spare_unit_id=u.id,
            spare_serial=sc, demand_code=dc, cost=cost,
            shipment_status="pending", signoff_status="pending")
        db.add(order)
        created_orders.append(order)
        if d.case_id:
            case = db.get(models.AftersalesCase, d.case_id)
            _add_event(db, case, "replacement", "待寄出",
                       f"指派方案 {plan.plan_no} 批准出库：{sc}", user, from_party="可用备件库存")

    plan.status = "approved"
    plan.approved_by_id = user.id
    plan.approved_at = now
    audit_svc.log(db, user.id, "as_plan_approved", "assignment_plan", plan.plan_no,
                  {"items": items})
    db.commit()
    return plan


# ---------------------------------------------------------------------------
# 替换件寄出（①）与客户签收（②）——互相独立
# ---------------------------------------------------------------------------

def ship_replacement(db: Session, order_id: int, user: models.User,
                     tracking_no: str = "") -> models.ReplacementOrder:
    order = db.get(models.ReplacementOrder, order_id)
    if not order:
        raise NotFoundError("替换件单不存在")
    if order.shipment_status == "shipped":
        raise BusinessRuleError("该替换件已寄出，不能重复寄出", code="already_shipped")
    order.shipment_status = "shipped"
    order.shipped_at = models.utcnow()
    order.shipped_by_id = user.id
    order.tracking_no = tracking_no or order.tracking_no or f"SF-{order.id:06d}"
    unit = db.get(models.SpareUnit, order.spare_unit_id)
    if unit:
        unit.status = "shipped"  # 已寄：撤案也不得恢复 available
    if order.case_id:
        case = db.get(models.AftersalesCase, order.case_id)
        _add_event(db, case, "replacement", "物流在途/客户",
                   f"替换件 {order.spare_serial} 已寄出（{order.tracking_no}）", user,
                   from_party="售后仓")
    audit_svc.log(db, user.id, "as_replacement_shipped", "replacement_order", str(order_id),
                  {"serial": order.spare_serial})
    db.commit()
    return order


def sign_replacement(db: Session, order_id: int, user: models.User,
                     signer: str = "客户") -> models.ReplacementOrder:
    order = db.get(models.ReplacementOrder, order_id)
    if not order:
        raise NotFoundError("替换件单不存在")
    if order.shipment_status != "shipped":
        raise BusinessRuleError("替换件尚未寄出，不能登记签收", code="not_shipped")
    if order.signoff_status == "signed":
        raise BusinessRuleError("客户已签收，不能重复登记", code="already_signed")
    order.signoff_status = "signed"
    order.signed_at = models.utcnow()
    order.signer = signer
    unit = db.get(models.SpareUnit, order.spare_unit_id)
    if unit:
        unit.status = "installed"
    if order.case_id:
        case = db.get(models.AftersalesCase, order.case_id)
        _add_event(db, case, "replacement", "客户（已签收安装）",
                   f"客户 {signer} 签收替换件 {order.spare_serial}", user, from_party="物流在途")
    audit_svc.log(db, user.id, "as_replacement_signed", "replacement_order", str(order_id),
                  {"serial": order.spare_serial, "signer": signer})
    db.commit()
    return order


def withdraw_case(db: Session, case_no: str, user: models.User) -> models.AftersalesCase:
    """撤案。已寄出的替换件绝不恢复可用；仅“已批准未寄出”的单子可冲销释放。"""
    case = get_case(db, case_no)
    if case.closed:
        raise BusinessRuleError("案件已结案，不能撤案", code="already_closed")
    orders = db.scalars(select(models.ReplacementOrder).where(
        models.ReplacementOrder.case_id == case.id)).all()
    for o in orders:
        unit = db.get(models.SpareUnit, o.spare_unit_id)
        if o.shipment_status == "shipped":
            # 核心规则：替换件已寄，不能靠撤案恢复可用
            if unit and unit.status == "available":
                # 理论不可能（寄出时已置 shipped），双保险
                raise BusinessRuleError("已寄出备件状态异常为可用，已拦截", code="integrity_error")
            audit_svc.log(db, user.id, "as_withdraw_keep_shipped", "replacement_order", str(o.id),
                          {"serial": o.spare_serial,
                           "message": "替换件已寄出，撤案不恢复库存可用状态"})
        else:
            # 未寄出：删除待寄单（无实物事件），释放备件与需求
            if unit:
                unit.status = "available"
            demand = db.scalar(select(models.AssignDemand).where(
                models.AssignDemand.code == o.demand_code)) if o.demand_code else None
            if demand and demand.fulfilled:
                demand.fulfilled = False
                demand.fulfilled_at = None
            db.delete(o)
    case.status = "withdrawn"
    audit_svc.log(db, user.id, "as_case_withdrawn", "aftersales_case", case.case_no)
    db.commit()
    return case


# ---------------------------------------------------------------------------
# 安全资格撤回 / 补库
# ---------------------------------------------------------------------------

def set_safety_qualification(db: Session, serial_no: str, user: models.User, *,
                            released: bool, note: str = "") -> models.SpareUnit:
    unit = db.scalar(select(models.SpareUnit).where(models.SpareUnit.serial_no == serial_no))
    if not unit:
        raise NotFoundError(f"备件 {serial_no} 不存在")
    unit.safety_released = released
    if note:
        unit.qualification_note = note
    audit_svc.log(db, user.id, "as_safety_qualification", "spare_unit", serial_no,
                  {"released": released, "note": note})
    db.commit()
    return unit


def restock_unit(db: Session, user: models.User, *, serial_no: str, batch: str,
                 model_code: str = "PM-X3", name: str = "兼容替换模组",
                 source: str = "restock") -> models.SpareUnit:
    exists = db.scalar(select(models.SpareUnit).where(models.SpareUnit.serial_no == serial_no))
    if exists:
        raise BusinessRuleError(f"序列号 {serial_no} 已存在，实物序列号必须唯一",
                                code="serial_exists")
    blocked = serial_no in terminal_repaired_serials(db)
    unit = models.SpareUnit(serial_no=serial_no, batch=batch, model_code=model_code,
                            name=name, status="available", safety_released=True, source=source,
                            whole_exchange_blocked=blocked,
                            qualification_note="该序列号有端子维修记录，禁止整机重复换出" if blocked else "")
    db.add(unit)
    audit_svc.log(db, user.id, "as_restock", "spare_unit", serial_no, {"batch": batch})
    db.commit()
    return unit


def add_compat_edge(db: Session, user: models.User, *, batch: str,
                    demand_code: str, supply_code: str, cost: int) -> models.CompatEdge:
    if cost < 0:
        raise BusinessRuleError("调配费用必须为非负整数", code="bad_cost")
    edge = db.scalar(select(models.CompatEdge).where(
        models.CompatEdge.batch == batch,
        models.CompatEdge.demand_code == demand_code,
        models.CompatEdge.supply_code == supply_code))
    if edge:
        edge.cost = cost
    else:
        edge = models.CompatEdge(batch=batch, demand_code=demand_code,
                                supply_code=supply_code, cost=cost)
        db.add(edge)
    audit_svc.log(db, user.id, "as_compat_edge_upsert", "compat_edge",
                  f"{demand_code}->{supply_code}", {"cost": cost})
    db.commit()
    return edge


# ---------------------------------------------------------------------------
# 结案门禁：实物待办 + 资金待办各自结清，材料/结论齐备
# ---------------------------------------------------------------------------

def closure_blockers(db: Session, case: models.AftersalesCase) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []

    if not case.materials_complete:
        blockers.append({"code": "materials_incomplete", "message": "申诉材料尚未标记收齐"})

    pending_checks = db.scalars(select(models.EngineeringCheck).where(
        models.EngineeringCheck.case_id == case.id,
        models.EngineeringCheck.status == "pending")).all()
    for chk in pending_checks:
        blockers.append({"code": "engineering_pending",
                         "message": f"工程补核项《{chk.title}》尚无结论（备注不能替代结论）"})

    if case.liability_status == "undetermined":
        blockers.append({"code": "liability_undetermined",
                         "message": "责任尚未由检测/工程结论确定（在保不等于责任成立）"})

    if case.downtime_started_at and not case.downtime_ended_at:
        blockers.append({"code": "downtime_open",
                         "message": "客户停机时段尚未登记结束，需确认设备/替换件已恢复运行"})

    orders = db.scalars(select(models.ReplacementOrder).where(
        models.ReplacementOrder.case_id == case.id)).all()
    ret = db.scalar(select(models.OldPartReturn).where(
        models.OldPartReturn.case_id == case.id))
    insp = db.scalar(select(models.ReworkInspection).where(
        models.ReworkInspection.case_id == case.id))
    dep = db.scalar(select(models.Deposit).where(models.Deposit.case_id == case.id))

    if case.path == "advance_replace":
        if not orders:
            blockers.append({"code": "no_replacement_order",
                             "message": "先换路径缺少已批准的替换件出库单"})
        for o in orders:
            if o.shipment_status != "shipped":
                blockers.append({"code": "replacement_not_shipped",
                                 "message": f"替换件 {o.spare_serial} 尚未寄出"})
            if o.signoff_status != "signed":
                blockers.append({"code": "replacement_not_signed",
                                 "message": f"替换件 {o.spare_serial} 客户尚未签收"})
        if not ret or ret.status != "received":
            blockers.append({"code": "old_part_not_received",
                             "message": "旧件尚未实际回收实收，实物去向未闭环"})
        elif ret.disposition == "pending":
            blockers.append({"code": "old_disposition_pending",
                             "message": "旧件已实收但最终处置/去向未登记"})
        if not dep or dep.status in ("pending",):
            blockers.append({"code": "deposit_unpaid",
                             "message": "先换路径押金未收讫"})
        elif dep.status == "paid":
            blockers.append({"code": "deposit_not_refunded",
                             "message": "押金仍在托管，资金待办未结清（需退款成功或扣除）"})
        elif dep.status in ("refund_pending", "refund_unknown"):
            blockers.append({"code": "deposit_refund_unknown",
                             "message": "押金退款结果未知，不能视为已退；须向通道查询确认"})
    else:
        # 先检后换：旧件 + 检测结论是硬前置
        if not ret or ret.status != "received":
            blockers.append({"code": "old_part_not_received",
                             "message": "先检路径必须先实收旧件"})
        else:
            if ret.disposition == "pending":
                blockers.append({"code": "old_disposition_pending",
                                 "message": "旧件已实收但最终处置/去向未登记"})
            if not insp or insp.status != "concluded":
                blockers.append({"code": "inspection_not_concluded",
                                 "message": "返修检测尚未出具结论，不能决定换货/退回/报废"})
            elif insp.result == "fault_confirmed" and not any(
                    o.signoff_status == "signed" for o in orders):
                blockers.append({"code": "exchange_not_completed",
                                 "message": "检测判定故障并决定换货，但替换件尚未完成签收"})
        if case.payment_held and not case.payment_resolved:
            blockers.append({"code": "payment_hold_open",
                             "message": "客户付款仍处暂缓状态，须放行/扣减/豁免后结清"})

    # 两条路径共同的资金门禁（先检路径也可能收押金）
    if dep and dep.status in ("refund_pending", "refund_unknown") and not any(
            b["code"] == "deposit_refund_unknown" for b in blockers):
        blockers.append({"code": "deposit_refund_unknown",
                         "message": "押金退款结果未知，不能视为已退"})
    if dep and dep.status == "paid" and case.path != "advance_replace":
        blockers.append({"code": "deposit_not_refunded", "message": "押金尚未退还/结清"})

    return blockers


def close_case(db: Session, case_no: str, user: models.User, note: str = "") -> models.AftersalesCase:
    case = get_case(db, case_no)
    if case.closed:
        raise BusinessRuleError("案件已结案", code="already_closed")
    if case.status == "withdrawn":
        raise BusinessRuleError("案件已撤案，不能再结案", code="withdrawn")
    blockers = closure_blockers(db, case)
    if blockers:
        raise BusinessRuleError(
            f"仍有 {len(blockers)} 项实物/资金/结论待办未结清，不能结案",
            code="closure_blocked", details={"blockers": blockers})
    case.closed = True
    case.status = "closed"
    case.closed_at = models.utcnow()
    case.closure_note = note
    audit_svc.log(db, user.id, "as_case_closed", "aftersales_case", case.case_no,
                  {"note": note, "preserved": "原申诉与工程解释继续保留可查"})
    db.commit()
    return case
