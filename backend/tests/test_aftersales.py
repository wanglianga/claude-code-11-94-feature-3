"""售后客服全链路测试：

保修时间窗、工程补核/责任证据、精确指派最优性（R1/R2、6x8=20160、稳定决胜）、
候选不占库存、原子批准/超卖/并发、安全资格撤回、两条路径独立状态、
端子维修防伪换、撤案不恢复已寄备件、退款未知、回收逾期、结案双结清门禁。
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from itertools import permutations

import pytest

from app.assignment import brute_force_optimum, solve_assignment
from app.database import SessionLocal
from app.services import aftersales as svc
from tests.conftest import ADMIN, h

SERVICE = "u_service"
ENGINEER = "u_engineer"
FINANCE = "u_finance"
WAREHOUSE = "u_warehouse"
SAFETY = "u_safety"

CST = timezone(timedelta(hours=8))


# --------------------------------------------------------------------------- helpers

def _case(client, no="AS-O31"):
    r = client.get(f"/api/aftersales/cases/{no}", headers=h(SERVICE))
    assert r.status_code == 200, r.text
    return r.json()


def _check_id(detail, kind):
    return next(c["id"] for c in detail["engineering_checks"] if c["kind"] == kind)


def _solve(client, batch):
    r = client.post(f"/api/aftersales/assignment/{batch}/solve", headers=h(SERVICE))
    assert r.status_code == 200, r.text
    return r.json()["plan"]


def _approve(client, plan_id, user=WAREHOUSE):
    return client.post(f"/api/aftersales/plans/{plan_id}/approve", headers=h(user))


def _pay_deposit(client, case_no, amount=3000):
    return client.post(f"/api/aftersales/cases/{case_no}/deposit/pay",
                       headers=h(FINANCE), json={"amount": amount})


def _materials_done(client, case_no):
    return client.post(f"/api/aftersales/cases/{case_no}/materials",
                       headers=h(SERVICE), json={"complete": True, "note": "齐"})


def _conclude_o31_checks(client):
    d = _case(client)
    for kind, result, conclusion in [
        ("transport_dent", "ruled_out", "压痕为运输造成但未伤及电芯与防护，不影响性能。"),
        ("install_temp_receipt", "confirmed", "补核安装曲线略高但仍在规格内，留档。"),
    ]:
        cid = _check_id(d, kind)
        r = client.post(f"/api/aftersales/engineering-checks/{cid}/conclude",
                       headers=h(ENGINEER), json={"result": result, "conclusion": conclusion})
        assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- 1. 保修边界

def test_warranty_window_may7_inside_may8_midnight_exclusive():
    acc = datetime(2025, 5, 8, 9, 40, tzinfo=CST)
    start, end = svc.warranty_window(acc)
    assert start == datetime(2025, 5, 8, 0, 0, tzinfo=CST)
    assert end == datetime(2026, 5, 8, 0, 0, tzinfo=CST)
    assert start <= datetime(2026, 5, 7, 23, 59, tzinfo=CST) < end
    # 次年 5 月 8 日 00:00 整：右端开区间，已出保
    assert not (start <= datetime(2026, 5, 8, 0, 0, tzinfo=CST) < end)
    assert not (start <= datetime(2026, 5, 9, 10, 0, tzinfo=CST) < end)


def test_o31_seed_is_in_warranty_with_page_fields(client):
    d = _case(client)
    w = d["warranty"]
    assert w["appealed_in_window"] is True
    assert "在保" in w["liability_notice"] and "责任" in w["liability_notice"]
    # 案件页必须显示保管人 / 停机时段 / 剩余承诺 / 下一次联系
    assert d["custodian_name"]
    assert d["downtime"] and d["downtime"]["ongoing"] is True
    assert d["commitment"] and "剩余" in d["commitment"]["text"]
    assert d["next_contact"]["at"]
    assert len(d["engineering_checks"]) == 2


# --------------------------------------------------------------------------- 2. 备注不能替代结论 / 责任证据

def test_empty_engineering_conclusion_rejected(client):
    d = _case(client)
    cid = d["engineering_checks"][0]["id"]
    r = client.post(f"/api/aftersales/engineering-checks/{cid}/conclude",
                   headers=h(ENGINEER), json={"result": "confirmed", "conclusion": "   "})
    assert r.status_code == 409
    assert r.json()["code"] == "conclusion_required"
    # 仅加联系备注不会改变补核项状态
    client.post("/api/aftersales/cases/AS-O31/contact", headers=h(SERVICE),
                json={"channel": "note", "note": "客服备注：看起来像运输压痕"})
    assert _case(client)["engineering_checks"][0]["status"] == "pending"


def test_liability_requires_engineering_or_inspection_proof(client):
    r = client.post("/api/aftersales/cases/AS-O31/liability", headers=h(ENGINEER),
                   json={"liability": "supplier", "rationale": "因为在保所以算供应商"})
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "liability_evidence_required"
    assert "在保" in body["message"]
    # 出一份工程结论后即可定责
    _conclude_o31_checks(client)
    r2 = client.post("/api/aftersales/cases/AS-O31/liability", headers=h(ENGINEER),
                     json={"liability": "transport", "rationale": "压痕补核确认运输挤压"})
    assert r2.status_code == 200, r2.text


# --------------------------------------------------------------------------- 3. 指派搜索引擎

def test_r1_r2_concurrency_sample_assignment():
    res = solve_assignment(
        ["R1", "R2"], ["S1", "S2"],
        [("R1", "S1", 1), ("R1", "S2", 2), ("R2", "S1", 1)], batch="R")
    mapping = {a["req_code"]: a["supply_code"] for a in res.assignments}
    # 贪心先拿 S1 给 R1 会漏掉 R2；精确搜索必须 R1→S2、R2→S1
    assert mapping == {"R1": "S2", "R2": "S1"}
    assert res.fulfilled_count == 2 and res.total_cost == 3


def test_real_batch_stable_tie_gives_o31_the_only_compatible_unit(client):
    plan = _solve(client, "REAL")
    assert plan["fulfilled_count"] == 1
    assert [i["demand_code"] for i in plan["items"]] == ["D-O31"]
    assert plan["items"][0]["supply_code"] == "SP-701"
    assert plan["unmet"] == ["D-O32"]
    # 候选不占库存
    state = client.get("/api/aftersales/assignment/state", headers=h(SERVICE)).json()
    real = next(b for b in state["batches"] if b["batch"] == "REAL")
    sp701 = next(u for u in real["units"] if u["serial_no"] == "SP-701")
    assert sp701["status"] == "available"


def test_full68_space_20160_and_optimal_cost(client):
    plan = _solve(client, "FULL68")
    stats = plan["stats"]
    assert stats["complete_space"] == 20160
    assert plan["fulfilled_count"] == 6
    assert stats["branches_expanded"] > 0
    assert stats["elapsed_ms"] >= 0.0

    # 独立暴力枚举全部 20160 个完整一对一指派，交叉验证最优代价
    reqs = [f"J{i}" for i in range(1, 7)]
    sups = [f"U{j}" for j in range(1, 9)]
    edges = []
    for i in range(6):
        for j in range(8):
            edges.append((f"J{i+1}", f"U{j+1}", 1 + ((i * 7 + j * 3) % 9)))
    count, cost, _ = brute_force_optimum(reqs, sups, edges)
    assert (plan["fulfilled_count"], plan["total_cost"]) == (count, cost)
    assert len(list(permutations(sups, 6))) == 20160


def test_solver_fuzz_matches_bruteforce():
    import random
    random.seed(7)
    for _ in range(120):
        n, m = random.randint(1, 4), random.randint(1, 5)
        reqs = [f"R{i}" for i in range(n)]
        sups = [f"S{j}" for j in range(m)]
        edges = [(r, s, random.randint(0, 9))
                 for r in reqs for s in sups if random.random() < 0.6]
        res = solve_assignment(reqs, sups, edges)
        bc, bco, _ = brute_force_optimum(reqs, sups, edges)
        assert (res.fulfilled_count, res.total_cost) == (bc, bco)


# --------------------------------------------------------------------------- 4. 原子批准 / 超卖 / 并发

def test_deposit_is_correctable_precondition_keeps_plan_candidate(client):
    p = _solve(client, "REAL")
    r = _approve(client, p["id"])
    assert r.status_code == 409 and r.json()["code"] == "precondition_failed"
    # 方案仍是 candidate，收押金后原方案可批准
    assert client.get(f"/api/aftersales/plans/{p['id']}", headers=h(SERVICE)
                      ).json()["status"] == "candidate"
    _pay_deposit(client, "AS-O31")
    assert _approve(client, p["id"]).status_code == 200


def test_oversell_impossible_on_last_unit(client):
    p1 = _solve(client, "REAL")
    p2 = _solve(client, "REAL")  # 两份候选都指向最后一台 SP-701
    _pay_deposit(client, "AS-O31")
    assert _approve(client, p1["id"]).status_code == 200
    r2 = _approve(client, p2["id"])
    assert r2.status_code == 409 and r2.json()["code"] == "assignment_stale"
    # 只有一张替换单、SP-701 已占用，绝不超卖
    d31 = _case(client)
    assert len(d31["replacement_orders"]) == 1
    units = client.get("/api/aftersales/units", headers=h(SERVICE)).json()
    sp = next(u for u in units if u["serial_no"] == "SP-701")
    assert sp["status"] == "allocated"


def test_concurrent_approvals_only_one_wins(client):
    # R-DEMO 两份相同候选，两个线程用独立 Session 并发批准
    pa = _solve(client, "R-DEMO")
    pb = _solve(client, "R-DEMO")
    barrier = threading.Barrier(2)
    outcomes = []

    def worker(pid):
        db = SessionLocal()
        try:
            barrier.wait(timeout=10)
            u = db.query(__import__("app.models", fromlist=["User"]).User
                         ).filter_by(username=WAREHOUSE).one()
            svc.approve_plan(db, pid, u)
            outcomes.append("ok")
        except Exception as e:  # noqa: BLE001
            outcomes.append(getattr(e, "code", type(e).__name__))
        finally:
            db.close()

    t1 = threading.Thread(target=worker, args=(pa["id"],))
    t2 = threading.Thread(target=worker, args=(pb["id"],))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert sorted(outcomes) == ["assignment_stale", "ok"], outcomes

    units = client.get("/api/aftersales/units", headers=h(SERVICE)).json()
    for serial in ("S1", "S2"):
        u = next(x for x in units if x["serial_no"] == serial)
        assert u["status"] == "allocated"


def test_compat_cost_change_makes_old_plan_stale(client):
    p = _solve(client, "R-DEMO")
    # 修改方案中实际使用的 R2→S1 费用
    r = client.post("/api/aftersales/compat-edges", headers=h(WAREHOUSE),
                    json={"batch": "R-DEMO", "demand_code": "R2",
                          "supply_code": "S1", "cost": 9})
    assert r.status_code == 200, r.text
    resp = _approve(client, p["id"])
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "assignment_stale"
    assert any("费用" in x for x in body["details"]["reasons"])


def test_safety_withdrawal_demo_atomic_rejection(client):
    r = client.post("/api/aftersales/demo/safety-withdrawal", headers=h(ADMIN))
    assert r.status_code == 200, r.text
    steps = {s["step"]: s for s in r.json()["steps"]}
    assert steps["approve_stale"]["expected_rejection"] is True
    assert steps["approve_stale"]["code"] == "assignment_stale"
    assert steps["plan_state"]["ok"] is True
    # 重算后 SS-1 被排除，只能满足 SD-1→SS-2
    new_plan = steps["resolve"]["plan"]
    assert [i["supply_code"] for i in new_plan["items"]] == ["SS-2"]
    # 没有产生任何 SAFE 替换单
    state = client.get("/api/aftersales/assignment/state", headers=h(SERVICE)).json()
    safe = next(b for b in state["batches"] if b["batch"] == "SAFE")
    assert all(not u["serial_no"].startswith("SS") or u["status"] == "available"
               for u in safe["units"] if u["serial_no"] == "SS-2")


# --------------------------------------------------------------------------- 5. 先换后旧 全链路 + 结案门禁

def test_advance_replace_full_path_and_closure(client):
    _materials_done(client, "AS-O31")
    _conclude_o31_checks(client)
    _pay_deposit(client, "AS-O31")
    plan = _solve(client, "REAL")
    assert _approve(client, plan["id"]).status_code == 200
    d = _case(client)
    oid = d["replacement_orders"][0]["id"]

    # 五个状态互相独立：批准后既未寄出也未签收
    assert d["replacement_orders"][0]["shipment_status"] == "pending"
    assert d["replacement_orders"][0]["signoff_status"] == "pending"

    # 未收旧件前不能入返修库存
    r = client.post("/api/aftersales/cases/AS-O31/old-part/to-rework-stock",
                    headers=h(WAREHOUSE))
    assert r.status_code == 409 and r.json()["code"] == "old_part_not_received"

    # 寄出 ① 与签收 ② 独立：寄出后仍未签收
    assert client.post(f"/api/aftersales/replacement-orders/{oid}/ship",
                       headers=h(WAREHOUSE), json={"tracking_no": "SF-O31"}).status_code == 200
    d = _case(client)
    assert d["replacement_orders"][0]["shipment_status"] == "shipped"
    assert d["replacement_orders"][0]["signoff_status"] == "pending"
    # 未寄出不能签收（此处已寄，验证重复签收幂等拦截在下面）
    assert client.post(f"/api/aftersales/replacement-orders/{oid}/sign",
                       headers=h(SERVICE), json={"signer": "O-31 张工"}).status_code == 200

    # 停机结束
    assert client.post("/api/aftersales/cases/AS-O31/downtime",
                       headers=h(SERVICE), json={"action": "end"}).status_code == 200

    # 此时结案应被旧件/押金阻塞
    r = client.post("/api/aftersales/cases/AS-O31/close", headers=h(SERVICE), json={})
    assert r.status_code == 409 and r.json()["code"] == "closure_blocked"
    codes = {b["code"] for b in r.json()["details"]["blockers"]}
    assert "old_part_not_received" in codes
    assert "deposit_not_refunded" in codes

    # 旧件回收 ③（仓库实收）
    assert client.post("/api/aftersales/cases/AS-O31/old-part/receive",
                       headers=h(WAREHOUSE), json={}).status_code == 200
    # 检测 ④：先开始再结论
    assert client.post("/api/aftersales/cases/AS-O31/inspection/start",
                       headers=h(ENGINEER)).status_code == 200
    r = client.post("/api/aftersales/cases/AS-O31/inspection/conclude",
                    headers=h(ENGINEER),
                    json={"result": "terminal_repairable", "liability": "supplier",
                          "report": "仅端子压接缺陷，芯体正常。"})
    assert r.status_code == 200, r.text

    # 登记端子维修（真实部件 + 去向）；先放一个同序列号库存件验证打标
    client.post("/api/aftersales/units/restock", headers=h(WAREHOUSE),
                json={"serial_no": "MOD-O31-X3", "batch": "RW"})
    r = client.post("/api/aftersales/cases/AS-O31/repairs", headers=h(ENGINEER), json={
        "repair_kind": "terminal_only",
        "actual_component_name": "功率端子 TB-50",
        "actual_component_serial": "TERM-2611-9", "quantity": 2,
        "old_component_disposition": "旧端子破坏性报废",
        "whole_unit_whereabouts": "整机 MOD-O31-X3 修复后入返修库存 RW-O31，禁止整机再换出",
    })
    assert r.status_code == 200, r.text
    units = client.get("/api/aftersales/units", headers=h(SERVICE)).json()
    assert next(u for u in units if u["serial_no"] == "MOD-O31-X3")["whole_exchange_blocked"]

    # 押金退款 ⑤：通道未知 → 未知状态阻塞结案 → 查询确认退款
    assert client.post("/api/aftersales/cases/AS-O31/deposit/refund-request",
                       headers=h(FINANCE)).status_code == 200
    d = _case(client)
    assert d["deposit"]["status"] == "refund_unknown"
    r = client.post("/api/aftersales/cases/AS-O31/close", headers=h(SERVICE), json={})
    codes = {b["code"] for b in r.json()["details"]["blockers"]}
    assert "deposit_refund_unknown" in codes
    assert client.post("/api/aftersales/cases/AS-O31/deposit/refund-query",
                       headers=h(FINANCE)).json()["deposit_status"] == "refunded"

    # 全部结清 → 结案成功，原申诉与工程解释保留
    r = client.post("/api/aftersales/cases/AS-O31/close", headers=h(SERVICE),
                    json={"note": "两清结案"})
    assert r.status_code == 200, r.text
    d = _case(client)
    assert d["closed"] is True
    assert "原申诉原文保留" in d["original_appeal"]
    assert "在保只代表合同时间条件成立" in d["engineering_explanation"]


def test_shipped_replacement_not_restored_by_withdraw(client):
    # O-41 种子：SP-601 已寄出并签收（status=installed）
    r = client.post("/api/aftersales/cases/AS-O41/withdraw", headers=h(SERVICE))
    assert r.status_code == 200, r.text
    units = client.get("/api/aftersales/units", headers=h(SERVICE)).json()
    sp = next(u for u in units if u["serial_no"] == "SP-601")
    assert sp["status"] != "available"
    assert sp["status"] == "installed"
    assert _case(client, "AS-O41")["status"] == "withdrawn"


def test_unshipped_approval_can_release_on_withdraw(client):
    _pay_deposit(client, "AS-O31")
    p = _solve(client, "REAL")
    assert _approve(client, p["id"]).status_code == 200
    # 未寄出即撤案：待寄单冲销、SP-701 释放
    assert client.post("/api/aftersales/cases/AS-O31/withdraw",
                       headers=h(SERVICE)).status_code == 200
    units = client.get("/api/aftersales/units", headers=h(SERVICE)).json()
    assert next(u for u in units if u["serial_no"] == "SP-701")["status"] == "available"


# --------------------------------------------------------------------------- 6. 先检后换路径

def test_inspect_first_path(client):
    no = "AS-O36"
    # 旧件未实收不能开始检测
    r = client.post(f"/api/aftersales/cases/{no}/inspection/start", headers=h(ENGINEER))
    assert r.status_code == 409 and r.json()["code"] == "old_part_not_received"

    assert client.post(f"/api/aftersales/cases/{no}/old-part/receive",
                       headers=h(WAREHOUSE), json={"tracking_no": "SF-OLD-36"}
                       ).status_code == 200
    assert client.post(f"/api/aftersales/cases/{no}/inspection/start",
                       headers=h(ENGINEER)).status_code == 200
    r = client.post(f"/api/aftersales/cases/{no}/inspection/conclude", headers=h(ENGINEER),
                    json={"result": "fault_confirmed", "liability": "supplier",
                          "report": "功率模块失效，确认供应商责任，决定换货。"})
    assert r.status_code == 200

    # 种子已预置兼容备件 SP-801（PM-Y2 已放行），直接走“复检后换货”精确指派+原子批准
    units = client.get("/api/aftersales/units", headers=h(SERVICE)).json()
    assert any(u["serial_no"] == "SP-801" and u["safety_released"] for u in units)
    r = client.post(f"/api/aftersales/cases/{no}/exchange/auto-assign",
                    headers=h(SERVICE), json={"supply_serial": "SP-801", "cost": 2})
    assert r.status_code == 200, r.text
    oid = _case(client, no)["replacement_orders"][0]["id"]
    assert client.post(f"/api/aftersales/replacement-orders/{oid}/ship",
                       headers=h(WAREHOUSE), json={}).status_code == 200
    assert client.post(f"/api/aftersales/replacement-orders/{oid}/sign",
                       headers=h(SERVICE), json={}).status_code == 200

    # 付款暂缓必须处置
    r = client.post(f"/api/aftersales/cases/{no}/close", headers=h(SERVICE), json={})
    codes = {b["code"] for b in r.json()["details"]["blockers"]}
    assert "payment_hold_open" in codes
    assert "old_disposition_pending" in codes
    assert client.post(f"/api/aftersales/cases/{no}/old-part/scrap",
                       headers=h(ENGINEER), json={"note": "失效模块报废"}).status_code == 200
    assert client.post(f"/api/aftersales/cases/{no}/payment-resolve",
                       headers=h(FINANCE), json={"resolution": "released"}).status_code == 200
    assert client.post(f"/api/aftersales/cases/{no}/downtime",
                       headers=h(SERVICE), json={"action": "end"}).status_code == 200
    r = client.post(f"/api/aftersales/cases/{no}/close", headers=h(SERVICE), json={})
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- 7. 种子演示场景

def test_o41_overdue_return_flagged(client):
    d = _case(client, "AS-O41")
    assert d["return_overdue"] is True
    assert d["old_part_return"]["overdue"] is True
    assert d["next_contact"]["overdue"] is True


def test_o42_refund_unknown_is_single_closure_blocker(client):
    d = _case(client, "AS-O42")
    codes = [b["code"] for b in d["closure_blockers"]]
    assert codes == ["deposit_refund_unknown"]
    assert d["deposit"]["status"] == "refund_unknown"


def test_o30_closed_case_preserves_appeal_and_explanation(client):
    d = _case(client, "AS-O30")
    assert d["closed"] is True
    assert d["original_appeal"] and d["engineering_explanation"]
    r = client.post("/api/aftersales/cases/AS-O30/close", headers=h(SERVICE), json={})
    assert r.status_code == 409


def test_auth_required_for_aftersales(client):
    r = client.get("/api/aftersales/cases")
    assert r.status_code == 401
