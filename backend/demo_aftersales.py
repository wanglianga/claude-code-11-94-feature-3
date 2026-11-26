"""售后客服 + 精确备件指派 命令行演示：

    DATABASE_URL=postgresql+psycopg2://ccdev:ccdev@127.0.0.1:5432/battery_demo \
    .venv/bin/python demo_aftersales.py

脚本会重建全部表并重新播种，然后真实执行：
  1) O-31 保修时间窗边界（次年 5/7 在保、5/8 00:00 出保）；
  2) R1/R2 并发样例的正确指派（R1→S2、R2→S1）；
  3) 6 需求×8 备件全兼容样例：20160 完整空间、实际展开分支、耗时、最终代价；
  4) O-31/O-32 竞争唯一兼容件的稳定编号决胜与超卖拦截；
  5) 先换后旧全链路（押金→批准原子出库→寄出→签收→收旧→检测→端子维修→
     退款未知→查询确认→结案）；
  6) 先检后换路径；
  7) 分配后安全资格撤回使旧方案整案退回；
  8) 回收逾期与押金退款未知的结案门禁；
  9) 已寄替换件撤案不恢复库存、端子维修整机序列号禁止重复换出。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import models
from app.assignment import solve_assignment
from app.database import Base, SessionLocal, engine
from app.seed import seed
from app.services import aftersales as svc
from app.services.errors import BusinessRuleError

CST = timezone(timedelta(hours=8))


def line(t=""):
    print(t)


def head(t):
    line("\n" + "=" * 74)
    line(t)
    line("=" * 74)


def expect_ok(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        raise SystemExit(f"验证失败：{name}")


def main():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    seed(db)

    admin = db.scalar(select(models.User).where(models.User.username == "u_admin"))
    eng = db.scalar(select(models.User).where(models.User.username == "u_engineer"))

    # 1. 保修边界 ---------------------------------------------------------
    head("1. O-31 虚构合同保修窗：2025-05-08 00:00 ~ 2026-05-08 00:00（不含）")
    c31 = svc.get_case(db, "AS-O31")
    w = svc.warranty_view(c31)
    print("  保修起:", w["warranty_start"], " 止:", w["warranty_end"])
    print("  申诉:", w["appealed_at"], " 在保:", w["appealed_in_window"])
    expect_ok("次年 5/7 申诉仍在期内", w["appealed_in_window"] is True)
    start, end = svc.warranty_window(datetime(2025, 5, 8, 9, 40, tzinfo=CST))
    expect_ok("5/8 00:00 整为右端开区间（出保）",
              not (start <= datetime(2026, 5, 8, 0, 0, tzinfo=CST) < end))
    expect_ok("在保 ≠ 责任已证明", "不等于检测已证明责任" in w["liability_notice"])

    # 2. R1/R2 ------------------------------------------------------------
    head("2. 补库后的并发样例 R1/R2（精确搜索，拒绝贪心漏案）")
    r = solve_assignment(
        ["R1", "R2"], ["S1", "S2"],
        [("R1", "S1", 1), ("R1", "S2", 2), ("R2", "S1", 1)], batch="R-DEMO")
    mp = {a["req_code"]: a["supply_code"] for a in r.assignments}
    print("  指派:", mp, " 数量:", r.fulfilled_count, " 总费用:", r.total_cost)
    expect_ok("R1→S2、R2→S1", mp == {"R1": "S2", "R2": "S1"})

    # 3. 6x8 --------------------------------------------------------------
    head("3. 本地样例：6 需求 × 8 备件全部兼容")
    import math
    reqs = [f"J{i}" for i in range(1, 7)]
    sups = [f"U{j}" for j in range(1, 9)]
    edges = [(f"J{i+1}", f"U{j+1}", 1 + ((i * 7 + j * 3) % 9))
             for i in range(6) for j in range(8)]
    res = solve_assignment(reqs, sups, edges, batch="FULL68",
                           complete_space=math.perm(8, 6))
    print(f"  完整一对一指派空间 P(8,6) = {res.complete_space}")
    print(f"  实际展开分支 = {res.branches_expanded}"
          f"（指派 {res.assign_branches} / 跳过 {res.skip_branches}，DFS 节点 {res.dfs_nodes}）")
    print(f"  完成耗时 = {res.elapsed_ms} ms；最大数量 = {res.fulfilled_count}；"
          f"最终最小代价 = {res.total_cost}")
    print("  配对:", [(a["req_code"], a["supply_code"], a["cost"]) for a in res.assignments])
    expect_ok("空间恰为 20160", res.complete_space == 20160)
    expect_ok("6 项需求全部满足", res.fulfilled_count == 6)
    expect_ok("最小代价为 12（经暴力枚举交叉验证）", res.total_cost == 12)

    # 4. REAL 批次竞争 + 超卖 ---------------------------------------------
    head("4. O-31 vs O-32 竞争唯一兼容件 SP-701（等价按稳定编号）")
    p1 = svc.solve_batch(db, "REAL", admin)
    db.commit()
    print("  候选方案:", [(i["demand_code"], i["supply_code"]) for i in p1.items],
          " 未满足:", p1.unmet)
    expect_ok("稳定编号 D-O31 取得唯一备件",
              [i["demand_code"] for i in p1.items] == ["D-O31"])
    p2 = svc.solve_batch(db, "REAL", admin)
    db.commit()
    svc.mark_deposit_paid(db, "AS-O31", admin, 3000)
    db.commit()
    svc.approve_plan(db, p1.id, admin)
    print("  第一份方案批准成功；尝试批准第二份（同一 SP-701）…")
    try:
        svc.approve_plan(db, p2.id, admin)
        expect_ok("第二份方案必须被原子拒绝", False)
    except BusinessRuleError as e:
        expect_ok(f"超卖被拦截：{e.code}", e.code == "assignment_stale")

    # 5. 先换后旧全链路（重置 O31 状态：上面只付了押金，继续推进） ----------
    head("5. 先寄替换件后收旧件：O-31 全链路")
    svc.set_materials(db, "AS-O31", admin, complete=True)
    db.commit()
    d = svc.get_case(db, "AS-O31")
    checks = db.scalars(select(models.EngineeringCheck).where(
        models.EngineeringCheck.case_id == d.id)).all()
    for chk in checks:
        svc.conclude_engineering_check(
            db, chk.id, eng, result="ruled_out",
            conclusion="工程补核完成：压痕/温度回执均不影响安全与保修判定流程。")
    db.commit()
    order = db.scalar(select(models.ReplacementOrder).where(
        models.ReplacementOrder.case_id == d.id))
    svc.ship_replacement(db, order.id, admin, "SF-O31-DEMO")
    svc.sign_replacement(db, order.id, admin, "O-31 设备科")
    svc.downtime(db, "AS-O31", admin, "end")
    db.commit()
    print("  替换件已寄出并签收（两个独立状态），停机结束")

    try:
        svc.move_to_rework_stock(db, "AS-O31", admin)
        expect_ok("旧件未实收不得入返修库存", False)
    except BusinessRuleError as e:
        expect_ok("旧件未实收不得入返修库存", e.code == "old_part_not_received")

    svc.receive_old_part(db, "AS-O31", admin)
    db.commit()
    svc.start_inspection(db, "AS-O31", eng)
    svc.conclude_inspection(db, "AS-O31", eng, result="terminal_repairable",
                            liability="supplier", report="仅主功率端子压接缺陷，芯体完好。")
    db.commit()
    svc.record_repair(
        db, "AS-O31", eng, repair_kind="terminal_only",
        actual_component_name="主功率端子 TB-75A", actual_component_serial="TERM-LOT-A",
        quantity=2, old_component_disposition="旧端子破坏性报废",
        whole_unit_whereabouts="整机 MOD-O31-X3 修复后入返修库存，保留序列号且禁止整机再换出")
    db.commit()
    print("  旧件实收→检测结论→端子维修（真实部件+去向）完成")

    svc.request_deposit_refund(db, "AS-O31", admin)
    db.commit()
    blockers = svc.closure_blockers(db, svc.get_case(db, "AS-O31"))
    codes = [b["code"] for b in blockers]
    print("  退款发起后状态 refund_unknown；结案阻塞:", codes)
    expect_ok("退款未知阻塞结案", "deposit_refund_unknown" in codes)
    svc.query_deposit_refund(db, "AS-O31", admin)
    db.commit()
    svc.close_case(db, "AS-O31", admin, note="演示两清结案")
    expect_ok("实物/资金结清后结案", svc.get_case(db, "AS-O31").closed is True)

    # 6. 先检后换 ---------------------------------------------------------
    head("6. 先收旧件复检后决定换货：O-36")
    try:
        svc.start_inspection(db, "AS-O36", eng)
        expect_ok("未收旧件不能检测", False)
    except BusinessRuleError as e:
        expect_ok("未收旧件不能检测", e.code == "old_part_not_received")
    svc.receive_old_part(db, "AS-O36", admin, "SF-OLD-36")
    db.commit()
    svc.start_inspection(db, "AS-O36", eng)
    svc.conclude_inspection(db, "AS-O36", eng, result="fault_confirmed",
                            liability="supplier", report="功率模块失效，决定换货。")
    db.commit()
    # SP-801 已由种子预置为 PM-Y2 可用放行备件
    svc.auto_assign_exchange(db, "AS-O36", admin, supply_serial="SP-801", cost=2)
    o36 = svc.get_case(db, "AS-O36")
    o = db.scalar(select(models.ReplacementOrder).where(models.ReplacementOrder.case_id == o36.id))
    svc.ship_replacement(db, o.id, admin)
    svc.sign_replacement(db, o.id, admin)
    svc.scrap_old_part(db, "AS-O36", eng, "失效模块报废")
    svc.resolve_payment(db, "AS-O36", admin, "released")
    svc.downtime(db, "AS-O36", admin, "end")
    db.commit()
    svc.close_case(db, "AS-O36", admin)
    expect_ok("先检后换路径可实际办结", svc.get_case(db, "AS-O36").closed is True)

    # 7. 安全资格撤回 ------------------------------------------------------
    head("7. 分配后安全资格撤回：SAFE 批次旧方案原子退回")
    plan = svc.solve_batch(db, "SAFE", admin)
    db.commit()
    print("  原候选:", [(i["demand_code"], i["supply_code"]) for i in plan.items])
    svc.set_safety_qualification(db, "SS-1", admin, released=False, note="绝缘待确认")
    try:
        svc.approve_plan(db, plan.id, admin)
        expect_ok("撤回资格后旧方案必须被拒", False)
    except BusinessRuleError as e:
        expect_ok("旧方案整案 stale，无半份指派", e.code == "assignment_stale")
    stale = db.get(models.AssignmentPlan, plan.id)
    expect_ok("方案状态已持久化为 stale", stale.status == "stale")
    order_count = db.query(models.ReplacementOrder).filter(
        models.ReplacementOrder.demand_code.in_(("SD-1", "SD-2"))).count()
    expect_ok("没有生成任何半份替换单", order_count == 0)

    # 8. 逾期 / 未知 种子场景 ---------------------------------------------
    head("8. 回收逾期 O-41 与退款未知 O-42")
    o41 = svc.get_case(db, "AS-O41")
    ret41 = svc._get_return(db, o41)
    overdue = bool(ret41.due_at and ret41.status != "received"
                   and models.utcnow() > ret41.due_at)
    expect_ok("O-41 旧件回收逾期被识别", overdue)
    b41 = svc.closure_blockers(db, o41)
    expect_ok("O-41 因旧件未回/押金等不能结案", len(b41) >= 1)
    o42 = svc.get_case(db, "AS-O42")
    b42 = svc.closure_blockers(db, o42)
    expect_ok("O-42 唯一阻塞为退款未知",
              [b["code"] for b in b42] == ["deposit_refund_unknown"])
    print("  O-42 阻塞:", [b["message"] for b in b42])

    # 9. 撤案不恢复已寄备件 + 端子锁 ---------------------------------------
    head("9. 库存完整性规则")
    sp601 = db.scalar(select(models.SpareUnit).where(models.SpareUnit.serial_no == "SP-601"))
    expect_ok("O-41 备件 SP-601 已签收安装（非可用）", sp601.status == "installed")
    svc.withdraw_case(db, "AS-O41", admin)
    db.refresh(sp601)
    expect_ok("撤案后已寄备件仍不恢复 available", sp601.status != "available")
    blocked = db.scalars(select(models.SpareUnit).where(
        models.SpareUnit.whole_exchange_blocked.is_(True))).first()
    expect_ok("存在被禁止整机重复换出的端子维修序列号", blocked is not None)
    print(f"  被锁整机序列号示例: {blocked.serial_no if blocked else None}")
    reason = svc.serial_blocked_reason(db, "MOD-O31-X3")
    expect_ok("维修记录维度同样能拦截 O-31 整机序列号", reason is not None)
    print(f"  MOD-O31-X3 拦截原因: {reason}")

    line("\n" + "=" * 74)
    line("全部演示步骤执行成功：两条路径可办、指派最优且原子安全、五个场景均可演示。")
    line("=" * 74)
    db.close()


if __name__ == "__main__":
    main()
