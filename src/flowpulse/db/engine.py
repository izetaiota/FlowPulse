"""数据库引擎与会话工厂（同步；个人部署量级，查询毫秒级，阻塞可忽略）。

PG 驱动用 psycopg v3（SQLAlchemy 2 原生支持 postgresql+psycopg://）。
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from flowpulse.db import models as _models  # noqa: F401 - 注册全部 ORM 映射
from flowpulse.db.base import Base


def create_engine_and_sessionmaker(database_url: str) -> tuple[Engine, sessionmaker[Session]]:
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    sessionmaker_ = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return engine, sessionmaker_


def ensure_tables(engine: Engine) -> None:
    """幂等建表（首次部署自动初始化；后续表结构演进走 Alembic）。"""
    Base.metadata.create_all(engine)
