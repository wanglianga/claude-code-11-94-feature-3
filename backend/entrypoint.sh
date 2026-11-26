#!/bin/sh
# 等待 PostgreSQL 就绪后启动服务（建表与播种在 FastAPI startup 中完成）
python - <<'PY'
import os
import socket
import time
from urllib.parse import urlparse

url = os.environ.get("DATABASE_URL", "")
# postgresql+psycopg2://user:pass@host:port/db
parsed = urlparse(url.replace("+psycopg2", ""))
host, port = parsed.hostname or "db", parsed.port or 5432

for i in range(60):
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"PostgreSQL {host}:{port} 已就绪")
            break
    except OSError:
        print(f"等待数据库 {host}:{port} … ({i + 1}/60)")
        time.sleep(2)
else:
    raise SystemExit("数据库连接超时")
PY

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
