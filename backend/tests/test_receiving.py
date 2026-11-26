"""收货与隔离规则测试"""
from tests.conftest import ADMIN, RECEIVER, SAFETY, h


def receive_pack(client, serial, batch="B-T1", events=None, slot="Q-1", team="收货一班"):
    return client.post("/api/receiving/scan", headers=h(RECEIVER), json={
        "batch_no": batch, "serial_no": serial, "oem": "测试车企",
        "source_vehicle": "VIN-1", "quarantine_slot": slot,
        "responsible_team": team, "events": events or [],
    })


def test_duplicate_scan_returns_original_receipt(client):
    r1 = receive_pack(client, "PK-100")
    assert r1.status_code == 200 and r1.json()["duplicated"] is False
    r2 = receive_pack(client, "PK-100")
    body = r2.json()
    assert body["duplicated"] is True
    assert "原收货单" in body["message"]
    assert body["receipt"]["id"] == r1.json()["receipt"]["id"]


def test_receipt_shows_slot_team_and_preconditions(client):
    r = receive_pack(client, "PK-101", events=[
        {"event_type": "collision", "source_doc": "COL-X", "case_closed": False}
    ])
    rec = r.json()["receipt"]
    assert rec["quarantine_slot"] == "Q-1"
    assert rec["responsible_team"] == "收货一班"
    pre = rec["pending_preconditions"]
    assert any("碰撞" in x for x in pre)


def test_batch_freeze_blocks_all_packs(client):
    for s in ("PK-1", "PK-2"):
        receive_pack(client, s, batch="B-F")
    r = client.post("/api/receiving/quarantine/batch", headers=h(ADMIN),
                    json={"batch_no": "B-F", "reason": "整批核验"})
    assert r.status_code == 200
    packs = client.get("/api/receiving/packs", headers=h(RECEIVER)).json()
    bf = [p for p in packs if p["serial_no"] in ("PK-1", "PK-2")]
    assert all(p["status"] == "quarantined" and p["frozen"] for p in bf)


def test_single_pack_quarantine_keeps_others_flowing(client):
    for s in ("PK-1", "PK-2"):
        receive_pack(client, s, batch="B-S")
    r = client.post("/api/receiving/quarantine/pack", headers=h(SAFETY),
                    json={"serial_no": "PK-1", "reason": "单包风险"})
    assert r.status_code == 200
    packs = {p["serial_no"]: p for p in client.get("/api/receiving/packs", headers=h(RECEIVER)).json()}
    assert packs["PK-1"]["status"] == "quarantined"
    assert packs["PK-2"]["status"] == "received" and packs["PK-2"]["frozen"] is False


def test_outbound_pack_cannot_be_quarantined_without_recall(client):
    # 走完整流程让 PK 出库
    receive_pack(client, "PK-O", batch="B-O")
    client.post("/api/safety/inspections", headers=h(SAFETY), json={
        "serial_no": "PK-O", "device_no": "DEV-OK",
        "insulation_pass": True, "bms_reading_ok": True})
    client.post("/api/safety/approvals", headers=h(SAFETY), json={
        "serial_no": "PK-O", "decision": "echelon", "purpose": "储能",
        "consignee": "买家甲", "quantity_limit": 1})
    outbound = client.get("/api/warehouse/outbound", headers=h(SAFETY)).json()[0]
    client.post("/api/warehouse/pick", headers=h("u_warehouse"),
                json={"picking_id": client.get("/api/warehouse/picking", headers=h(SAFETY)).json()[0]["id"]})
    client.post("/api/warehouse/ship", headers=h("u_warehouse"),
                json={"outbound_id": outbound["id"]})
    r = client.post("/api/receiving/quarantine/pack", headers=h(SAFETY),
                    json={"serial_no": "PK-O", "reason": "尝试隔离"})
    assert r.status_code == 409
    assert "召回或退运" in r.json()["message"]


def test_role_enforcement(client):
    r = client.post("/api/receiving/scan", headers=h("u_warehouse"), json={
        "batch_no": "X", "serial_no": "Y", "oem": "o", "source_vehicle": "v"})
    assert r.status_code == 401
