from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .database import Base, engine
from .routers import aftersales, audit, auth, dismantling, receiving, safety, scenario, warehouse
from .services.errors import AuthError, BusinessRuleError, NotFoundError

settings = get_settings()

app = FastAPI(title=settings.app_name, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(BusinessRuleError)
async def business_handler(_: Request, exc: BusinessRuleError):
    content = {"ok": False, "code": exc.code, "message": exc.message}
    if exc.details:
        content["details"] = exc.details
    return JSONResponse(status_code=409, content=content)


@app.exception_handler(NotFoundError)
async def not_found_handler(_: Request, exc: NotFoundError):
    return JSONResponse(status_code=404, content={"ok": False, "message": exc.message})


@app.exception_handler(AuthError)
async def auth_handler(_: Request, exc: AuthError):
    return JSONResponse(status_code=401, content={"ok": False, "message": exc.message})


app.include_router(auth.router)
app.include_router(receiving.router)
app.include_router(dismantling.router)
app.include_router(safety.router)
app.include_router(warehouse.router)
app.include_router(scenario.router)
app.include_router(audit.router)
app.include_router(aftersales.router)


@app.get("/")
def root():
    return {"app": settings.app_name, "status": "running", "docs": "/docs"}


@app.on_event("startup")
def on_startup():
    # 本地演示：自动建表并播种；生产环境应改用迁移工具
    Base.metadata.create_all(bind=engine)
    from .database import SessionLocal
    from .seed import seed

    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
