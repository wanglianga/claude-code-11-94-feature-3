"""L-7 场景命令行演示：

    DATABASE_URL=postgresql+psycopg2://ccdev:ccdev@127.0.0.1:5432/battery_demo \
    .venv/bin/python demo_l7.py

脚本会建表播种并输出两种隔离策略对比、P-3 迟到浸水、P-1 换标失配的验证结果。
仿真在独立事务中回滚，不改变演示库中的种子数据。
"""
from sqlalchemy import select

from app import models
from app.database import Base, SessionLocal, engine
from app.seed import seed
from app.services import scenario


def main():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    seed(db)

    users = {}
    for role in ("admin", "safety", "dismantler", "warehouse"):
        users[role] = db.scalar(
            select(models.User).where(models.User.role == role)
        )
    db.close()

    result = scenario.run_comparison(lambda: SessionLocal(), users)

    bf = result["batch_freeze_strategy"]
    sp = result["single_pack_strategy"]

    print("=" * 70)
    print("策略一：整批冻结")
    print(f"  可放行的包: {bf['releasable']}")
    print(f"  审批尝试: {[(a['pack'], a['result']) for a in bf['approval_attempts']]}")
    print(f"  待拣货单数量: {bf['picking_count']}")
    print(f"  买家通知数量: {bf['buyer_notification_count']}")
    print("  结论:", result["conclusion"]["batch_freeze"])

    print("=" * 70)
    print("策略二：单包隔离")
    print(f"  初始可放行: {sp['releasable_at_start']}")
    print(f"  初始待拣货单数量: {sp['picking_count_at_start']}")
    print(f"  初始买家通知数量: {sp['buyer_notification_count_at_start']}")
    late = sp["after_late_water_p3"]
    print("  P-3 迟到浸水后:")
    print(f"    P-3 拣货尝试: {late['p3_pick_attempt']}")
    print(f"    仍可流转的包: {late['still_flowing_packs']}")
    print(f"    更正通知数: {sum(1 for n in late['notifications'] if n['corrected'])}")
    rel = sp["after_relabel_mismatch_p1"]
    print("  P-1 换标失配:")
    print(f"    未知模组: {rel['unknown_module']}")
    print(f"    工单关闭尝试: {rel['work_order_close_attempt']}")
    print("  结论:", result["conclusion"]["single_pack"])
    print("=" * 70)


if __name__ == "__main__":
    main()
