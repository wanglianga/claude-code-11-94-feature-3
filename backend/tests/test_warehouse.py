"""仓库、签收、召回、核对与 L-7 场景测试"""
from tests.conftest import ADMIN, DISMANTLER, DISMANTLER2, DOWNSTREAM, SAFETY, WAREHOUSE, h


def _prepare_echelon(client, serial, batch="B-W"):
    client.post("/api/receiving/scan", headers=h("u_receiver"), json={
        "batch_no": batch, "serial_no": serial, "oem": "车企",
        "source_vehicle": "VIN", "quarantine_slot": "Q", "responsible_team": "班"})
    client.post("/api/safety/inspections", headers=h(SAFETY), json={
        "serial_no": serial, "device_no": "DEV-OK",
        "insulation_pass": True, "bms_reading_ok": True})
    client.post("/api/safety/approvals", headers=h(SAFETY), json={
        "serial_no": serial, "decision": "echelon", "purpose": "储能",
        "consignee": "买家甲", "quantity_limit": 1})


def test_pick_ship_sign_happy_path(client):
    _prepare_echelon(client, "PK-H")
    picking = client.get("/api/warehouse/picking", headers=h(SAFETY)).json()[0]
    r = client.post("/api/warehouse/pick", headers=h(WAREHOUSE),
                    json={"picking_id": picking["id"]})
    assert r.status_code == 200 and r.json()["picking"]["status"] == "picked"
    outbound = client.get("/api/warehouse/outbound", headers=h(SAFETY)).json()[0]
    r = client.post("/api/warehouse/ship", headers=h(WAREHOUSE),
                    json={"outbound_id": outbound["id"]})
    assert r.status_code == 200
    r = client.post("/api/warehouse/sign-off", headers=h(DOWNSTREAM), json={
        "outbound_id": outbound["id"], "action": "signed", "signer": "周买家"})
    assert r.status_code == 200


def test_buyer_rejection_returns_to_quarantine_not_stock(client):
    _prepare_echelon(client, "PK-REJ")
    picking = client.get("/api/warehouse/picking", headers=h(SAFETY)).json()[0]
    client.post("/api/warehouse/pick", headers=h(WAREHOUSE), json={"picking_id": picking["id"]})
    outbound = client.get("/api/warehouse/outbound", headers=h(SAFETY)).json()[0]
    client.post("/api/warehouse/ship", headers=h(WAREHOUSE), json={"outbound_id": outbound["id"]})
    r = client.post("/api/warehouse/sign-off", headers=h(DOWNSTREAM), json={
        "outbound_id": outbound["id"], "action": "rejected",
        "signer": "周买家", "note": "外观损伤"})
    assert r.status_code == 200
    pack = [p for p in client.get("/api/receiving/packs", headers=h(SAFETY)).json()
            if p["serial_no"] == "PK-REJ"][0]
    assert pack["status"] == "quarantined" and pack["frozen"] is True
    # 不能直接再批准（隔离中）
    r = client.post("/api/safety/approvals", headers=h(SAFETY), json={
        "serial_no": "PK-REJ", "decision": "echelon", "purpose": "x",
        "consignee": "y", "quantity_limit": 1})
    assert r.status_code == 409


def test_shipped_goods_cannot_be_deleted_but_can_recall(client):
    _prepare_echelon(client, "PK-RC")
    picking = client.get("/api/warehouse/picking", headers=h(SAFETY)).json()[0]
    client.post("/api/warehouse/pick", headers=h(WAREHOUSE), json={"picking_id": picking["id"]})
    outbound = client.get("/api/warehouse/outbound", headers=h(SAFETY)).json()[0]
    client.post("/api/warehouse/ship", headers=h(WAREHOUSE), json={"outbound_id": outbound["id"]})
    # 历史仍可查
    assert client.get("/api/warehouse/outbound", headers=h(SAFETY)).json()
    r = client.post("/api/warehouse/recall", headers=h(ADMIN), json={
        "outbound_id": outbound["id"], "kind": "recall", "reason": "发现批次性风险"})
    assert r.status_code == 200
    pack = [p for p in client.get("/api/receiving/packs", headers=h(SAFETY)).json()
            if p["serial_no"] == "PK-RC"][0]
    assert pack["status"] == "quarantined"


def test_reconciliation_blocks_close_with_unexplained_difference(client):
    _prepare_echelon(client, "PK-N1", batch="B-REC")
    # 已批准但未发货 -> 放行 1、已发 0，有差额
    r = client.post("/api/warehouse/close-batch", headers=h(ADMIN),
                    json={"batch_no": "B-REC"})
    assert r.status_code == 409 and "差额" in r.json()["message"]
    # 提供解释后可结清
    picking = client.get("/api/warehouse/picking", headers=h(SAFETY)).json()[0]
    client.post("/api/warehouse/pick", headers=h(WAREHOUSE), json={"picking_id": picking["id"]})
    outbound = client.get("/api/warehouse/outbound", headers=h(SAFETY)).json()[0]
    client.post("/api/warehouse/ship", headers=h(WAREHOUSE), json={"outbound_id": outbound["id"]})
    r2 = client.post("/api/warehouse/close-batch", headers=h(ADMIN),
                     json={"batch_no": "B-REC"})
    assert r2.status_code == 200


def test_l7_seed_and_strategy_comparison(client):
    packs = {p["serial_no"]: p for p in client.get("/api/receiving/packs", headers=h(SAFETY)).json()}
    assert set(s for s in packs if s.startswith("P-")) == {"P-1", "P-2", "P-3", "P-4"}
    # P-1 有碰撞且未复检 -> 门禁
    blockers = client.get("/api/safety/echelon-blockers/P-1", headers=h(SAFETY)).json()
    assert blockers["blocked"] is True and any("碰撞" in b for b in blockers["blockers"])
    # 策略对比（回滚仿真，不改变真实数据）
    r = client.post("/api/scenario/l7/compare", headers=h(ADMIN))
    assert r.status_code == 200
    data = r.json()
    bf = data["batch_freeze_strategy"]
    sp = data["single_pack_strategy"]
    # 整批冻结：全部挡住
    assert bf["releasable"] == []
    assert bf["picking_count"] == 0 and bf["buyer_notification_count"] == 0
    # 单包隔离：P-2/P-3/P-4 可先放行
    assert set(sp["releasable_at_start"]) == {"P-2", "P-3", "P-4"}
    assert sp["picking_count_at_start"] == 3
    assert sp["buyer_notification_count_at_start"] == 3
    # P-3 迟到浸水：旧单失效、拣货被阻止、P-2/P-4 继续
    late = sp["after_late_water_p3"]
    assert late["p3_pick_attempt"]["result"] == "blocked"
    assert set(late["still_flowing_packs"]) == {"P-2", "P-4"}
    assert any(n["corrected"] for n in late["notifications"])
    # P-1 失配换标：待核工单 + 未知模组
    rel = sp["after_relabel_mismatch_p1"]
    assert rel["work_order_close_attempt"]["result"] == "blocked"
    assert rel["unknown_module"]["unknown_parent"] is True
    assert rel["unknown_module"]["pack_id"] is None
    # 仿真已回滚：真实 P-3 仍为待审批、无新增通知更正
    packs_after = {p["serial_no"]: p for p in client.get("/api/receiving/packs", headers=h(SAFETY)).json()}
    assert packs_after["P-3"]["status"] == "pending_approval"
    notes = client.get("/api/warehouse/notifications", headers=h(SAFETY)).json()
    assert all(n["corrected"] is False for n in notes)
