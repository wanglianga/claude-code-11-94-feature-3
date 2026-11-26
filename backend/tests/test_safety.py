"""安全放行硬门禁测试：校准过期、绝缘失败、热事件、BMS 不可抵消、退回补检失效"""
from datetime import datetime, timedelta, timezone

from tests.conftest import ADMIN, DISMANTLER, DISMANTLER2, SAFETY, WAREHOUSE, h


def _receive(client, serial, batch="B-SF", events=None):
    return client.post("/api/receiving/scan", headers=h("u_receiver"), json={
        "batch_no": batch, "serial_no": serial, "oem": "车企",
        "source_vehicle": "VIN", "quarantine_slot": "Q", "responsible_team": "班",
        "events": events or []})


def _inspect(client, serial, device="DEV-OK", insulation=True, bms=True, reinspect=False):
    return client.post("/api/safety/inspections", headers=h(SAFETY), json={
        "serial_no": serial, "device_no": device,
        "insulation_pass": insulation, "bms_reading_ok": bms,
        "is_reinspection": reinspect})


def _approve_echelon(client, serial):
    return client.post("/api/safety/approvals", headers=h(SAFETY), json={
        "serial_no": serial, "decision": "echelon", "purpose": "储能调峰",
        "consignee": "华东储能", "quantity_limit": 1})


def test_collision_not_offset_by_bms(client):
    _receive(client, "PK-C", events=[
        {"event_type": "collision", "source_doc": "COL-1", "case_closed": False}])
    _inspect(client, "PK-C", bms=True, insulation=True)  # BMS 正常
    r = _approve_echelon(client, "PK-C")
    assert r.status_code == 409
    assert "碰撞" in r.json()["message"] and "BMS" in r.json()["message"]


def test_reinspection_pass_clears_collision(client):
    _receive(client, "PK-C2", events=[
        {"event_type": "collision", "source_doc": "COL-2", "case_closed": False}])
    _inspect(client, "PK-C2")
    r_block = _approve_echelon(client, "PK-C2")
    assert r_block.status_code == 409
    # 复检合格
    _inspect(client, "PK-C2", reinspect=True)
    r_ok = _approve_echelon(client, "PK-C2")
    assert r_ok.status_code == 200


def test_water_event_same_rule(client):
    _receive(client, "PK-W", events=[
        {"event_type": "water", "source_doc": "WAT-1"}])
    _inspect(client, "PK-W", bms=True)
    r = _approve_echelon(client, "PK-W")
    assert r.status_code == 409 and "浸水" in r.json()["message"]
    _inspect(client, "PK-W", reinspect=True)
    assert _approve_echelon(client, "PK-W").status_code == 200


def test_expired_calibration_blocks(client):
    _receive(client, "PK-E")
    _inspect(client, "PK-E", device="DEV-EXPIRED")
    r = _approve_echelon(client, "PK-E")
    assert r.status_code == 409 and "校准" in r.json()["message"]


def test_insulation_failure_blocks(client):
    _receive(client, "PK-I")
    _inspect(client, "PK-I", insulation=False, bms=True)
    r = _approve_echelon(client, "PK-I")
    assert r.status_code == 409 and "绝缘" in r.json()["message"]


def test_open_thermal_event_blocks(client):
    _receive(client, "PK-T", events=[
        {"event_type": "thermal", "source_doc": "TH-1", "case_closed": False}])
    _inspect(client, "PK-T")
    r = _approve_echelon(client, "PK-T")
    assert r.status_code == 409 and "热事件" in r.json()["message"]
    # 结案后放行
    events = client.get("/api/receiving/packs", headers=h(SAFETY)).json()
    ev_id = [p for p in events if p["serial_no"] == "PK-T"][0]["transport_events"][0]["id"]
    client.post("/api/safety/thermal/close", headers=h(SAFETY),
                json={"event_id": ev_id, "closed": True})
    assert _approve_echelon(client, "PK-T").status_code == 200


def test_echelon_requires_purpose_consignee_quantity(client):
    _receive(client, "PK-Q")
    _inspect(client, "PK-Q")
    r = client.post("/api/safety/approvals", headers=h(SAFETY), json={
        "serial_no": "PK-Q", "decision": "echelon"})
    assert r.status_code == 409 and "用途" in r.json()["message"]


def test_reinspect_voids_old_approval_and_corrects_downstream(client):
    _receive(client, "PK-V")
    _inspect(client, "PK-V")
    appr = _approve_echelon(client, "PK-V").json()["approval"]
    # 已生成拣货单与买家通知
    picking = client.get("/api/warehouse/picking", headers=h(SAFETY)).json()
    assert picking and picking[0]["status"] == "waiting"
    notes = client.get("/api/warehouse/notifications", headers=h(SAFETY)).json()
    assert notes and notes[0]["corrected"] is False
    # 退回补检
    r = client.post("/api/safety/approvals", headers=h(SAFETY), json={
        "serial_no": "PK-V", "decision": "reinspect", "rationale": "补充浸水复检"})
    assert r.status_code == 200
    # 旧放行单失效
    approvals = client.get("/api/safety/approvals", headers=h(SAFETY)).json()
    old = [a for a in approvals if a["id"] == appr["id"]][0]
    assert old["status"] == "voided"
    # 拣货单被更正、买家收到更正通知
    picking2 = client.get("/api/warehouse/picking", headers=h(SAFETY)).json()
    assert picking2[0]["status"] == "corrected"
    notes2 = client.get("/api/warehouse/notifications", headers=h(SAFETY)).json()
    assert any(n["corrected"] is True and "更正" in n["message"] for n in notes2)
    # 仓库不能拣该单
    r = client.post("/api/warehouse/pick", headers=h(WAREHOUSE),
                    json={"picking_id": picking2[0]["id"]})
    assert r.status_code == 409


def test_unknown_parent_module_blocks_echelon(client):
    _receive(client, "PK-UM")
    wo = client.post("/api/dismantling/work-orders", headers=h(DISMANTLER),
                     json={"serial_no": "PK-UM"}).json()["work_order"]["id"]
    client.post("/api/dismantling/unknown-module", headers=h(DISMANTLER), json={
        "work_order_id": wo, "module_serial": "M-X", "reason": "失配"})
    _inspect(client, "PK-UM")
    r = _approve_echelon(client, "PK-UM")
    assert r.status_code == 409 and "父子关系" in r.json()["message"]
