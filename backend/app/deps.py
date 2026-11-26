"""鉴权依赖：简化的 X-Username 头 + 角色校验（演示系统，账号见种子数据）。"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from . import models
from .database import get_db
from .services.errors import AuthError


def get_current_user(
    x_username: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> models.User:
    if not x_username:
        raise AuthError("缺少 X-Username 请求头，请先登录")
    user = db.query(models.User).filter(models.User.username == x_username).first()
    if not user:
        raise AuthError(f"用户 {x_username} 不存在")
    return user


def require_roles(*roles: str) -> Callable:
    def checker(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role not in roles:
            raise AuthError(f"角色 {user.role} 无权执行该操作，需要：{'/'.join(roles)}")
        return user
    return checker
