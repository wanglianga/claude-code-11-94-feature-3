"""初始化种子数据：角色账号、检测设备、样例批次 L-7（P-1~P-4）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .enums import PackStatus
from .seed_aftersales import DEMO_USERS, seed_aftersales
from .services import receiving, safety
from .services.errors import BusinessRuleError

SEED_USERS = [
    ("u_receiver", "王接收", "receiver", "收货一班"),
    ("u_dismantler", "李拆解", "dismantler", "拆解一班"),
    ("u_dismantler2", "赵拆解", "dismantler", "拆解二班"),
    ("u_safety", "陈安全", "safety", "安全工程组"),
    ("u_warehouse", "孙仓储", "warehouse", "仓储班"),
    ("u_downstream", "周买家", "downstream", "华东储能公司"),
    ("u_admin", "管理员", "admin", "中心管理组"),
] + DEMO_USERS


def seed(db: Session) -> dict:
    created = {"users": 0, "devices": 0, "batch": None, "packs": []}
    user_map: dict[str, models.User] = {}
    for username, display_name, role, team in SEED_USERS:
        u = db.scalar(select(models.User).where(models.User.username == username))
        if not u:
            u = models.User(username=username, display_name=display_name, role=role, team=team)
            db.add(u)
            created["users"] += 1
        user_map[username] = u
    db.flush()

    # 售后客服域种子（幂等，独立于 L-7 是否已经播种）
    seed_aftersales(db, user_map)

    now = datetime.now(timezone.utc)
    dev_ok = db.scalar(select(models.Device).where(models.Device.device_no == "DEV-OK"))
    if not dev_ok:
        dev_ok = models.Device(device_no="DEV-OK", name="绝缘/BMS 综合检测台 A",
                               calibrated_until=now + timedelta(days=365))
        db.add(dev_ok)
        created["devices"] += 1
    dev_exp = db.scalar(select(models.Device).where(models.Device.device_no == "DEV-EXPIRED"))
    if not dev_exp:
        dev_exp = models.Device(device_no="DEV-EXPIRED", name="旧检测台 B（校准过期）",
                                calibrated_until=now - timedelta(days=30))
        db.add(dev_exp)
        created["devices"] += 1
    db.flush()

    if db.scalar(select(models.Batch).where(models.Batch.batch_no == "L-7")):
        db.commit()
        created["batch"] = "L-7 已存在，跳过场景播种"
        return created

    receiver = user_map["u_receiver"]
    common = dict(batch_no="L-7", oem="远景车企", source_vehicle="车辆 VIN-L7-2026",
                  scan_payload="scanner-v1")
    # P-1：碰撞记录且未复检
    p1, _, _ = receiving.receive_pack(
        db, user=receiver, serial_no="P-1",
        quarantine_slot="Q-A-01", responsible_team="收货一班",
        events=[{"event_type": "collision", "description": "运输途中右侧碰撞",
                 "source_doc": "COL-2026-001", "case_closed": False}],
        **common,
    )
    # P-2~P-4：身份链完整、无共同热事件
    for idx, slot in enumerate(("Q-A-02", "Q-A-03", "Q-A-04"), start=2):
        receiving.receive_pack(
            db, user=receiver, serial_no=f"P-{idx}",
            quarantine_slot=slot, responsible_team="收货一班", events=[], **common,
        )
    db.flush()

    # P-2~P-4 检测合格（合格设备、绝缘通过、BMS 正常）
    for serial in ("P-2", "P-3", "P-4"):
        pack = db.scalar(select(models.Pack).where(models.Pack.serial_no == serial))
        rec = models.InspectionRecord(
            pack_id=pack.id, device_id=dev_ok.id, is_reinspection=False,
            insulation_pass=True, bms_reading_ok=True, result="pass",
            inspector_id=user_map["u_safety"].id, note="出厂初检合格",
        )
        db.add(rec)
        pack.status = PackStatus.pending_approval.value
    db.commit()

    created["batch"] = "L-7"
    created["packs"] = ["P-1", "P-2", "P-3", "P-4"]
    return created
