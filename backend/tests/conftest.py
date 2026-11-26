import os

os.environ["DATABASE_URL"] = "postgresql+psycopg2://ccdev:ccdev@127.0.0.1:5432/battery_test"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine, SessionLocal
from app.main import app
from app.seed import seed


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    seed(db)
    db.close()
    with TestClient(app) as c:
        yield c


def h(username):
    return {"X-Username": username}


RECEIVER = "u_receiver"
DISMANTLER = "u_dismantler"
DISMANTLER2 = "u_dismantler2"
SAFETY = "u_safety"
WAREHOUSE = "u_warehouse"
DOWNSTREAM = "u_downstream"
ADMIN = "u_admin"
