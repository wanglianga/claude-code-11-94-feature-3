"""售后模块固定种子数据（本批已批准需求、物理库存、兼容表与五个演示场景）。

幂等：以 AS-O31 是否存在为标记；reset_aftersales 可清空后重建。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .services.aftersales import CST, warranty_window

DEMO_USERS = [
    ("u_service", "冯售后", "service", "售后客服组"),
    ("u_engineer", "蒋工程", "engineer", "工程补核组"),
    ("u_finance", "钱财务", "finance", "财务退款组"),
]


def _dt(y: int, mo: int, d: int, h: int = 10, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=CST)


def reset_aftersales(db: Session) -> None:
    """清空售后域数据（保留用户与既有电池业务数据），用于演示重置。"""
    for model in (
        models.RepairRecord, models.ReworkInspection, models.OldPartReturn,
        models.ReplacementOrder, models.CustodyEvent, models.CaseContact,
        models.EngineeringCheck, models.Deposit, models.AssignmentPlan,
        models.CompatEdge, models.AssignDemand, models.SpareUnit,
        models.AftersalesCase,
    ):
        db.query(model).delete()
    db.commit()


def seed_aftersales(db: Session, users: dict[str, models.User]) -> dict:
    if db.scalar(select(models.AftersalesCase).where(
            models.AftersalesCase.case_no == "AS-O31")):
        return {"aftersales": "已存在，跳过"}

    now = models.utcnow()
    svc = users["u_service"]
    eng = users["u_engineer"]
    wh = users["u_warehouse"]
    fin = users.get("u_finance") or users["u_admin"]

    # ------------------------------------------------------------------ cases
    def make_case(**kw) -> models.AftersalesCase:
        c = models.AftersalesCase(**kw)
        db.add(c)
        db.flush()
        return c

    # O-31：保修时间窗标杆案件（2025-05-08 验收，2026-05-07 申诉仍在期内）
    acc31 = _dt(2025, 5, 8, 9, 40)
    ws31, we31 = warranty_window(acc31)
    c31 = make_case(
        case_no="AS-O31", customer_code="O-31",
        title="模组输出异常致停机，客户要求保修先换",
        path="advance_replace", module_serial="MOD-O31-X3", module_model="PM-X3",
        accepted_at=acc31, warranty_start=ws31, warranty_end=we31,
        appealed_at=_dt(2026, 5, 7, 16, 20),
        original_appeal=(
            "客户 O-31 申诉：2026-05-07 现场 3 号模组输出异常、产线停机，"
            "要求按保修先寄兼容替换件，旧模组随后寄回复检，并询问押金与保修范围。"
            "（原申诉原文保留，任何后续处理不得覆盖）"),
        engineering_explanation=(
            "合同保修自 2025-05-08 00:00 起至 2026-05-08 00:00 前，"
            "客户 2026-05-07 申诉在保修时间窗内。但在保只代表合同时间条件成立，"
            "不代表检测已证明属于保修责任：模组外壳的运输压痕需要工程人员补核是否影响性能，"
            "安装温度回执缺失需要补核安装工况。客服备注不能替代这两项结论，"
            "结论出具前责任状态保持“未确定”。"),
        liability_status="undetermined",
        materials_complete=False,
        downtime_started_at=now - timedelta(hours=5),
        commitment_deadline=now + timedelta(hours=26),
        commitment_note="承诺 24 小时内给出替换/检测方案",
        next_contact_at=now + timedelta(hours=2),
        next_contact_note="回电确认押金支付与停机影响",
        custodian_party="customer", custodian_name="客户 O-31 现场",
    )
    db.add(models.EngineeringCheck(
        case_id=c31.id, kind="transport_dent", title="运输压痕补核",
        description="模组右下角可见运输压痕照片，需工程人员核对压痕是否伤及电芯/防护等级。",
        status="pending"))
    db.add(models.EngineeringCheck(
        case_id=c31.id, kind="install_temp_receipt", title="安装温度回执补核",
        description="档案中缺少安装当次温度回执，需补核安装温度是否超出规格。",
        status="pending"))
    db.add(models.Deposit(case_id=c31.id, amount=3000, status="pending"))
    db.add(models.OldPartReturn(
        case_id=c31.id, whole_serial="MOD-O31-X3", status="not_sent",
        due_at=now + timedelta(days=6)))
    db.add(models.CustodyEvent(
        case_id=c31.id, scope="old_part", to_party="客户 O-31 现场",
        note="验收交付后旧/在役模组由客户保管", actor_id=svc.id))

    # O-32：与 O-31 竞争唯一兼容备件的第二案（押金已付，稳定编号靠后而落选）
    acc32 = _dt(2025, 6, 12, 14, 0)
    ws32, we32 = warranty_window(acc32)
    c32 = make_case(
        case_no="AS-O32", customer_code="O-32",
        title="同型号模组通讯告警，申请先换",
        path="advance_replace", module_serial="MOD-O32-X3", module_model="PM-X3",
        accepted_at=acc32, warranty_start=ws32, warranty_end=we32,
        appealed_at=_dt(2026, 5, 20, 10, 5),
        original_appeal="客户 O-32 申诉：同型号模组通讯间歇告警，申请先寄替换件。",
        engineering_explanation="同批次 PM-X3，兼容备件与 O-31 共用，需参与多案精确指派。",
        liability_status="undetermined", materials_complete=True,
        downtime_started_at=now - timedelta(hours=26),
        commitment_deadline=now + timedelta(hours=22),
        commitment_note="承诺 48 小时内解决",
        next_contact_at=now + timedelta(hours=5), next_contact_note="告知备件指派结果",
        custodian_party="customer", custodian_name="客户 O-32 现场")
    db.add(models.Deposit(case_id=c32.id, amount=3000, status="paid",
                         paid_at=now - timedelta(hours=20), gateway_ref="PAY-O32-01"))
    db.add(models.OldPartReturn(
        case_id=c32.id, whole_serial="MOD-O32-X3", status="not_sent",
        due_at=now + timedelta(days=7)))

    # O-36：先收旧件复检后决定换货（停机中、旧件在途、付款暂缓）
    acc36 = _dt(2025, 9, 12, 11, 0)
    ws36, we36 = warranty_window(acc36)
    c36 = make_case(
        case_no="AS-O36", customer_code="O-36",
        title="先检后换：功率跌落，客户同意先寄回复检",
        path="inspect_first", module_serial="MOD-O36-Y2", module_model="PM-Y2",
        accepted_at=acc36, warranty_start=ws36, warranty_end=we36,
        appealed_at=_dt(2026, 9, 10, 9, 30),
        original_appeal="客户 O-36 申诉：功率跌落约 18%，接受先收旧件复检、凭结论决定是否换货。",
        engineering_explanation="已排除安装温度问题；等待旧件实收后台架复检。",
        liability_status="undetermined", materials_complete=True,
        downtime_started_at=now - timedelta(hours=30),
        commitment_deadline=now + timedelta(hours=16),
        commitment_note="旧件实收后 24 小时内出检测结论",
        next_contact_at=now + timedelta(hours=3), next_contact_note="跟进物流签收",
        custodian_party="logistics", custodian_name="顺丰 SF-OLD-36 在途",
        payment_held=True, payment_hold_reason="复检结论与责任明确前，暂缓本期配件款支付")
    db.add(models.EngineeringCheck(
        case_id=c36.id, kind="install_temp_receipt", title="安装温度回执补核",
        description="安装温度回执齐全，工程补核未发现超温。",
        status="concluded", result="ruled_out",
        conclusion="核对安装曲线，端子温度峰值 61℃，低于 75℃ 规格上限，排除安装超温。",
        engineer_id=eng.id, concluded_at=now - timedelta(days=2)))
    db.add(models.OldPartReturn(
        case_id=c36.id, whole_serial="MOD-O36-Y2", status="in_transit",
        tracking_no="SF-OLD-36", sent_at=now - timedelta(days=1),
        due_at=now + timedelta(days=4)))
    db.add(models.ReworkInspection(case_id=c36.id, status="not_started"))
    db.add(models.Deposit(case_id=c36.id, amount=0, status="not_required"))
    # 预置一件 PM-Y2 已放行备件，复检结论后可直接输入 SP-801 走“精确指派并批准”
    db.add(models.SpareUnit(serial_no="SP-801", batch="CASE-EX", model_code="PM-Y2",
                            name="PM-Y2 兼容替换模组（O-36 复检后换货备用）",
                            status="available", safety_released=True, source="stock"))

    # O-41：回收逾期演示（替换件已寄已签，旧件超过承诺寄回期限）
    c41 = make_case(
        case_no="AS-O41", customer_code="O-41",
        title="替换件已签收，旧件寄回逾期",
        path="advance_replace", module_serial="MOD-O41-X3", module_model="PM-X3",
        accepted_at=_dt(2025, 3, 3, 10), warranty_start=_dt(2025, 3, 3, 0),
        warranty_end=_dt(2026, 3, 3, 0), appealed_at=_dt(2026, 2, 20, 15),
        original_appeal="客户 O-41：通讯故障申诉，已按先换路径收到替换件。",
        engineering_explanation="工程补核确认外壳压痕为运输导致但不影响性能，责任待商务判定。",
        liability_status="transport",
        liability_basis="工程补核结论：压痕为运输挤压造成，电气性能测试合格，运输责任。",
        liability_by_id=eng.id, liability_at=now - timedelta(days=10),
        materials_complete=True,
        downtime_started_at=now - timedelta(days=12),
        downtime_ended_at=now - timedelta(days=9),
        commitment_deadline=now + timedelta(days=2),
        commitment_note="尽快追回逾期旧件并完成押金退款",
        next_contact_at=now - timedelta(hours=8), next_contact_note="已过计划联系时间，立即催寄旧件",
        custodian_party="customer", custodian_name="客户 O-41（旧件待寄回，已逾期）")
    db.add(models.EngineeringCheck(
        case_id=c41.id, kind="transport_dent", title="运输压痕补核",
        status="concluded", result="confirmed",
        conclusion="压痕形态与运输挤压一致；壳体防护未失效、电气性能合格，不影响安全。",
        engineer_id=eng.id, concluded_at=now - timedelta(days=10)))
    u601 = models.SpareUnit(serial_no="SP-601", batch="CASE-O41", model_code="PM-X3",
                            status="installed", safety_released=True, source="stock")
    db.add(u601)
    db.flush()
    db.add(models.ReplacementOrder(
        case_id=c41.id, spare_unit_id=u601.id, spare_serial="SP-601",
        demand_code="", cost=1, shipment_status="shipped",
        tracking_no="SF-601", shipped_at=now - timedelta(days=10),
        signoff_status="signed", signed_at=now - timedelta(days=9), signer="O-41 前台"))
    db.add(models.OldPartReturn(
        case_id=c41.id, whole_serial="MOD-O41-X3", status="not_sent",
        due_at=now - timedelta(days=3)))
    db.add(models.Deposit(case_id=c41.id, amount=3000, status="paid",
                         paid_at=now - timedelta(days=11), gateway_ref="PAY-O41"))

    # O-42：押金退款结果未知演示（实物已结清，唯一结案阻塞是资金状态未知）
    c42 = make_case(
        case_no="AS-O42", customer_code="O-42",
        title="仅端子损坏已修复，押金退款通道结果未知",
        path="advance_replace", module_serial="MOD-O42-X3", module_model="PM-X3",
        accepted_at=_dt(2025, 4, 18, 10), warranty_start=_dt(2025, 4, 18, 0),
        warranty_end=_dt(2026, 4, 18, 0), appealed_at=_dt(2026, 3, 2, 11),
        original_appeal="客户 O-42：端子烧蚀导致接触不良，同意先换并寄回旧件。",
        engineering_explanation="检测确认仅功率端子烧蚀，芯体完好，做端子级维修并记录真实部件去向。",
        liability_status="supplier",
        liability_basis="返修检测：端子批次压接缺陷，供应商责任。",
        liability_by_id=eng.id, liability_at=now - timedelta(days=5),
        materials_complete=True,
        downtime_started_at=now - timedelta(days=14),
        downtime_ended_at=now - timedelta(days=12),
        commitment_deadline=now + timedelta(hours=12),
        commitment_note="退款对账完成后结案",
        next_contact_at=now + timedelta(days=1), next_contact_note="财务次工作日对账",
        custodian_party="lab", custodian_name="返修检测区（整机修复待入库）")
    u602 = models.SpareUnit(serial_no="SP-602", batch="CASE-O42", model_code="PM-X3",
                            status="installed", safety_released=True, source="stock")
    db.add(u602)
    db.flush()
    db.add(models.ReplacementOrder(
        case_id=c42.id, spare_unit_id=u602.id, spare_serial="SP-602",
        cost=1, shipment_status="shipped", tracking_no="SF-602",
        shipped_at=now - timedelta(days=13),
        signoff_status="signed", signed_at=now - timedelta(days=12), signer="O-42 设备科"))
    db.add(models.OldPartReturn(
        case_id=c42.id, whole_serial="MOD-O42-X3", status="received",
        sent_at=now - timedelta(days=10), received_at=now - timedelta(days=8),
        disposition="terminal_repair",
        disposition_note="端子维修完成，整机入返修库存，不作为整机备件重复换出"))
    db.add(models.ReworkInspection(
        case_id=c42.id, status="concluded", result="terminal_repairable",
        liability="supplier", inspector_id=eng.id,
        started_at=now - timedelta(days=8), concluded_at=now - timedelta(days=7),
        report="开盖检查芯体正常，仅主功率端子压接部位烧蚀；更换端子组件并做拉力/温升复测合格。"))
    db.add(models.RepairRecord(
        case_id=c42.id, old_whole_serial="MOD-O42-X3", repair_kind="terminal_only",
        actual_component_name="主功率端子组件 TB-75A",
        actual_component_serial="TERM-LOT-2603-A", quantity=2,
        old_component_disposition="旧烧蚀端子拆下后破坏性报废，留存照片 RCPT-42",
        whole_unit_whereabouts="整机 MOD-O42-X3 端子修复+复测合格，入返修库存 RW-O42，"
                               "保留原整机序列号且禁止作为整机再次换出",
        note="只修端子，不更换模组整机；真实部件批次可追溯。", technician_id=eng.id))
    db.add(models.Deposit(
        case_id=c42.id, amount=3000, status="refund_unknown", gateway_ref="RF-AS-O42",
        paid_at=now - timedelta(days=13),
        refund_requested_at=now - timedelta(days=1, hours=2),
        unknown_since=now - timedelta(days=1)))
    # 端子修复后的原整机：实物存在但永久禁止作为整机重复换出
    db.add(models.SpareUnit(
        serial_no="MOD-O42-X3", batch="RW-O42", model_code="PM-X3",
        name="O-42 端子修复整机（仅换端子，非整机替换）",
        status="available", safety_released=True, source="rework",
        whole_exchange_blocked=True,
        qualification_note="仅做端子级维修，保留原整机序列号，禁止作为整机再次换出"))

    # O-30：已结案参考案（原申诉与工程解释仍保留可查）
    c30 = make_case(
        case_no="AS-O30", customer_code="O-30", title="已结案参考：无故障原机退回",
        path="inspect_first", module_serial="MOD-O30-Y2", module_model="PM-Y2",
        accepted_at=_dt(2025, 1, 10, 10), warranty_start=_dt(2025, 1, 10, 0),
        warranty_end=_dt(2026, 1, 10, 0), appealed_at=_dt(2025, 12, 15, 10),
        original_appeal="客户 O-30：偶发报错，申请检测。",
        engineering_explanation="复检无故障，软件阈值误报，升级后原机退回。",
        liability_status="customer", liability_basis="检测无故障，属现场软件配置问题。",
        liability_by_id=eng.id, liability_at=now - timedelta(days=20),
        materials_complete=True,
        downtime_started_at=now - timedelta(days=40),
        downtime_ended_at=now - timedelta(days=38),
        custodian_party="customer", custodian_name="客户 O-30（原机已退回）",
        payment_held=False, payment_resolved=True, payment_resolution="released",
        closed=True, status="closed", closed_at=now - timedelta(days=18),
        closure_note="实物原机退回签收、付款暂缓解除，无押金；材料齐备，结案。")
    db.add(models.OldPartReturn(
        case_id=c30.id, whole_serial="MOD-O30-Y2", status="received",
        received_at=now - timedelta(days=25), disposition="returned_customer",
        disposition_note="复检无故障，原整机退回客户并签收"))
    db.add(models.ReworkInspection(
        case_id=c30.id, status="concluded", result="no_fault", liability="customer",
        report="台架 72h 无复现，升级固件阈值后正常。", inspector_id=eng.id,
        concluded_at=now - timedelta(days=22)))

    # ------------------------------------------------------------- assignment
    # REAL 批次：本批已批准需求 + 物理库存 + 固定兼容表
    for code, case in (("D-O31", c31), ("D-O32", c32)):
        db.add(models.AssignDemand(batch="REAL", code=code, case_id=case.id, approved=True))
    db.add(models.SpareUnit(serial_no="SP-701", batch="REAL", model_code="PM-X3",
                            name="PM-X3 兼容替换模组（O-31 唯一兼容件）",
                            status="available", safety_released=True))
    db.add(models.SpareUnit(serial_no="SP-702", batch="REAL", model_code="PM-X9",
                            name="PM-X9 模组（与本批需求不兼容）",
                            status="available", safety_released=True))
    db.add(models.CompatEdge(batch="REAL", demand_code="D-O31", supply_code="SP-701", cost=1))
    db.add(models.CompatEdge(batch="REAL", demand_code="D-O32", supply_code="SP-701", cost=1))

    # R-DEMO：补库后的并发样例（R1 可用 S1 费用1 / S2 费用2；R2 只能 S1 费用1）
    db.add(models.AssignDemand(batch="R-DEMO", code="R1", approved=True, title="并发需求 R1"))
    db.add(models.AssignDemand(batch="R-DEMO", code="R2", approved=True, title="并发需求 R2"))
    for s in ("S1", "S2"):
        db.add(models.SpareUnit(serial_no=s, batch="R-DEMO", model_code="DEMO",
                                status="available", safety_released=True, source="sample"))
    db.add(models.CompatEdge(batch="R-DEMO", demand_code="R1", supply_code="S1", cost=1))
    db.add(models.CompatEdge(batch="R-DEMO", demand_code="R1", supply_code="S2", cost=2))
    db.add(models.CompatEdge(batch="R-DEMO", demand_code="R2", supply_code="S1", cost=1))

    # FULL68：6 需求 × 8 备件全部兼容，完整一对一空间 P(8,6)=20160
    for i in range(1, 7):
        db.add(models.AssignDemand(batch="FULL68", code=f"J{i}", approved=True))
    for j in range(1, 9):
        db.add(models.SpareUnit(serial_no=f"U{j}", batch="FULL68", model_code="ALL",
                                status="available", safety_released=True, source="sample"))
    for i in range(6):
        for j in range(8):
            cost = 1 + ((i * 7 + j * 3) % 9)  # 固定整数费用表（与测试期望一致：最优代价 12）
            db.add(models.CompatEdge(batch="FULL68", demand_code=f"J{i+1}",
                                     supply_code=f"U{j+1}", cost=cost))

    # SAFE：安全资格撤回演示专用（拓扑同 R 样例）
    db.add(models.AssignDemand(batch="SAFE", code="SD-1", approved=True))
    db.add(models.AssignDemand(batch="SAFE", code="SD-2", approved=True))
    for s in ("SS-1", "SS-2"):
        db.add(models.SpareUnit(serial_no=s, batch="SAFE", model_code="DEMO",
                                status="available", safety_released=True, source="sample"))
    db.add(models.CompatEdge(batch="SAFE", demand_code="SD-1", supply_code="SS-1", cost=1))
    db.add(models.CompatEdge(batch="SAFE", demand_code="SD-1", supply_code="SS-2", cost=2))
    db.add(models.CompatEdge(batch="SAFE", demand_code="SD-2", supply_code="SS-1", cost=1))

    db.flush()
    return {"aftersales": "seeded"}
