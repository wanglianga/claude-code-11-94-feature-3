"""拆解、双方见证、换标、未知模组规则测试"""
from tests.conftest import ADMIN, DISMANTLER, DISMANTLER2, SAFETY, h


def _receive(client, serial="PK-D", batch="B-D"):
    client.post("/api/receiving/scan", headers=h("u_receiver"), json={
        "batch_no": batch, "serial_no": serial, "oem": "车企",
        "source_vehicle": "VIN", "quarantine_slot": "Q", "responsible_team": "班"})


def _work_order(client, serial):
    r = client.post("/api/dismantling/work-orders", headers=h(DISMANTLER),
                    json={"serial_no": serial})
    return r.json()["work_order"]["id"]


def test_two_witness_link_creates_parent_child(client):
    _receive(client)
    wo = _work_order(client, "PK-D")
    r = client.post("/api/dismantling/link-module", headers=h(DISMANTLER), json={
        "work_order_id": wo, "module_serial": "M-1",
        "witness1": DISMANTLER, "witness2": DISMANTLER2})
    assert r.status_code == 200
    m = r.json()["module"]
    assert m["unknown_parent"] is False and m["status"] == "linked"


def test_same_witness_rejected(client):
    _receive(client, "PK-D2")
    wo = _work_order(client, "PK-D2")
    r = client.post("/api/dismantling/link-module", headers=h(DISMANTLER), json={
        "work_order_id": wo, "module_serial": "M-2",
        "witness1": DISMANTLER, "witness2": DISMANTLER})
    assert r.status_code == 409 and "两名不同操作者" in r.json()["message"]


def test_duplicate_module_serial_rejected(client):
    _receive(client, "PK-D3")
    wo = _work_order(client, "PK-D3")
    payload = {"work_order_id": wo, "module_serial": "M-DUP",
               "witness1": DISMANTLER, "witness2": DISMANTLER2}
    client.post("/api/dismantling/link-module", headers=h(DISMANTLER), json=payload)
    r = client.post("/api/dismantling/link-module", headers=h(DISMANTLER), json=payload)
    assert r.status_code == 409


def test_unknown_module_quarantined_and_blocks_work_order(client):
    _receive(client, "PK-U")
    wo = _work_order(client, "PK-U")
    r = client.post("/api/dismantling/unknown-module", headers=h(DISMANTLER), json={
        "work_order_id": wo, "module_serial": "M-UNKNOWN-1",
        "reason": "重贴标签无法匹配"})
    assert r.status_code == 200
    m = r.json()["module"]
    assert m["unknown_parent"] is True and m["status"] == "quarantine_review"
    # 工单不能关闭
    r = client.post(f"/api/dismantling/work-orders/{wo}/complete", headers=h(DISMANTLER))
    assert r.status_code == 409 and "隔离待核" in r.json()["message"]
    # 绝不能自动归到最相似序列号：列表中 pack_id 保持 None
    mods = client.get("/api/dismantling/modules", headers=h(SAFETY)).json()
    got = [x for x in mods if x["serial_no"] == "M-UNKNOWN-1"][0]
    assert got["pack_id"] is None


def test_resolve_unknown_after_manual_verification(client):
    _receive(client, "PK-R")
    wo = _work_order(client, "PK-R")
    client.post("/api/dismantling/unknown-module", headers=h(DISMANTLER), json={
        "work_order_id": wo, "module_serial": "M-UN2", "reason": "x"})
    r = client.post("/api/dismantling/resolve-unknown", headers=h(SAFETY), json={
        "module_serial": "M-UN2", "parent_serial": "PK-R"})
    assert r.status_code == 200 and r.json()["module"]["unknown_parent"] is False


def test_relabel_requires_two_different_operators_and_keeps_history(client):
    _receive(client, "PK-L")
    # 第一人发起
    r1 = client.post("/api/dismantling/relabel", headers=h(DISMANTLER), json={
        "entity_type": "pack", "old_serial": "PK-L", "new_serial": "PK-L-NEW"})
    assert r1.status_code == 200 and r1.json()["confirmed"] is False
    # 同一人不能确认
    r_same = client.post("/api/dismantling/relabel", headers=h(DISMANTLER), json={
        "entity_type": "pack", "old_serial": "PK-L", "new_serial": "PK-L-NEW",
        "operator2": DISMANTLER, "confirm": True})
    assert r_same.status_code == 409
    # 第二人确认后生效
    r2 = client.post("/api/dismantling/relabel", headers=h(DISMANTLER2), json={
        "entity_type": "pack", "old_serial": "PK-L", "new_serial": "PK-L-NEW",
        "operator2": DISMANTLER2, "confirm": True})
    assert r2.status_code == 200 and r2.json()["confirmed"] is True
    hist = client.get("/api/dismantling/label-history", headers=h(SAFETY)).json()
    entry = [x for x in hist if x["old_serial"] == "PK-L"][0]
    assert entry["new_serial"] == "PK-L-NEW"
    assert entry["operator1_id"] is not None and entry["operator2_id"] is not None
    # 旧号已查不到实体，新号可用
    packs = client.get("/api/receiving/packs", headers=h(SAFETY)).json()
    assert any(p["serial_no"] == "PK-L-NEW" for p in packs)
    assert not any(p["serial_no"] == "PK-L" for p in packs)


def test_dismantling_blocked_when_frozen(client):
    _receive(client, "PK-F")
    client.post("/api/receiving/quarantine/pack", headers=h(ADMIN),
                json={"serial_no": "PK-F", "reason": "冻结"})
    r = client.post("/api/dismantling/work-orders", headers=h(DISMANTLER),
                    json={"serial_no": "PK-F"})
    assert r.status_code == 409
