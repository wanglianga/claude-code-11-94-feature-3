from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..schemas import LoginIn
from ..serializers import user_out

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(models.User).where(models.User.username == body.username))
    if not user:
        return {"ok": False, "message": f"用户 {body.username} 不存在", "user": None}
    return {"ok": True, "message": "登录成功（前端后续请求带 X-Username 头）", "user": user_out(user)}


@router.get("/me")
def me(user: models.User = Depends(get_current_user)):
    return user_out(user)


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    # 演示系统的无密码账号清单：登录页在尚无 X-Username 时也要能拉取，故不要求鉴权
    return [user_out(u) for u in db.scalars(select(models.User).order_by(models.User.id)).all()]
