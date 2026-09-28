"""
SQLAlchemy 异步引擎（业务表专用）

与 core/postgres.py 的分工见该文件说明。

连接串要转换：psycopg 原生用 postgresql://，SQLAlchemy 要 postgresql+psycopg://
（只配一个 POSTGRES_DSN，这里改前缀，避免两处维护）
"""
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from core.config import settings
from models.tables import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None


def _sqlalchemy_url() -> str:
    """把 psycopg 风格的 DSN 转成 SQLAlchemy 的驱动前缀"""
    url = settings.POSTGRES_DSN
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


async def init_database() -> None:
    """建引擎 + 会话工厂 + 建表（幂等）"""
    global _engine, _session_factory
    if _engine is not None:
        return

    _engine = create_async_engine(
        _sqlalchemy_url(),
        pool_size=5,
        max_overflow=5,
        # 取连接前先探活：PG 重启后不把死连接交给业务
        pool_pre_ping=True,
    )
    # expire_on_commit=False：commit 后对象属性仍可读（否则出参会触发额外查询）
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def get_session_factory() -> async_sessionmaker:
    """会话工厂（服务层每个方法自开会话，用完即还）"""
    if _session_factory is None:
        raise RuntimeError("数据库未初始化：应用 lifespan 未执行")
    return _session_factory


async def dispose_engine() -> None:
    """应用关闭时释放连接池（幂等）"""
    global _engine, _session_factory
    engine, _engine, _session_factory = _engine, None, None
    if engine is not None:
        await engine.dispose()
