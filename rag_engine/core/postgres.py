"""
PostgreSQL 连接池 + LangGraph checkpointer

与 core/database.py 分工：
- 这里：LangGraph checkpoint（框架状态），走 psycopg 原生驱动
- 那里：业务表（conversations 等），走 SQLAlchemy ORM

为什么 checkpoint 不 ORM 化：AsyncPostgresSaver 是 LangGraph 自己的实现，
表和读写逻辑都由框架管理，不参与 ORM 映射。
"""
import asyncio
from contextlib import suppress

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from core.config import settings

_pool: AsyncConnectionPool | None = None
_checkpointer: AsyncPostgresSaver | None = None
# 并发首次请求时避免重复建池。注意是 asyncio.Lock——不能和 dependencies.py 里
# 给同步 Chroma 用的 threading.Lock 混用（后者在 async 函数里会阻塞事件循环）
_init_lock = asyncio.Lock()


def _make_pool() -> AsyncConnectionPool:
    """构造连接池（不打开）。

    kwargs 必须与 AsyncPostgresSaver.from_conn_string 内部保持一致，
    否则 saver 取列时会抛 TypeError: tuple indices must be integers or slices, not str
    """
    return AsyncConnectionPool(
        conninfo=settings.POSTGRES_DSN,
        min_size=settings.PG_POOL_MIN,
        max_size=settings.PG_POOL_MAX,
        # 显式 False：默认值会隐式打开连接池并发出 RuntimeWarning
        open=False,
        # 默认 check=None 不做任何检查，PG 重启后池里的死连接会被直接发出去
        check=AsyncConnectionPool.check_connection,
        kwargs={
            "autocommit": True,       # setup() 里的 CREATE INDEX CONCURRENTLY 不能在事务里
            "row_factory": dict_row,  # saver 用 row["col"] 取值
            "prepare_threshold": 0,   # 与官方 from_conn_string 内部一致
        },
    )


async def open_pool_with_retry(attempts: int = 10, base_delay: float = 1.0) -> AsyncConnectionPool:
    """建池并等待 PG 就绪（递增退避重试）。

    每次重试必须新建池对象：open(wait=True) 超时时 psycopg-pool 会先把池关掉再抛异常，
    而已关闭的池不允许重新打开（PoolClosed）。
    """
    last_exc: Exception | None = None
    for i in range(1, attempts + 1):
        pool = _make_pool()
        try:
            await pool.open(wait=True, timeout=10.0)
            return pool
        except Exception as e:
            last_exc = e
            with suppress(Exception):
                await pool.close()
            delay = min(base_delay * i, 10.0)
            print(f"⚠️ PostgreSQL 未就绪（{i}/{attempts}）: "
                  f"{type(e).__name__}: {e}；{delay:.1f}s 后重试")
            if i < attempts:
                await asyncio.sleep(delay)

    raise RuntimeError(f"PostgreSQL 在 {attempts} 次尝试后仍不可用") from last_exc


async def init_checkpointer() -> AsyncPostgresSaver:
    """建池 → 构造 saver → 建表（幂等）

    必须在运行中的事件循环里调用：AsyncPostgresSaver.__init__ 内部会执行
    asyncio.get_running_loop()，在模块导入期构造会 RuntimeError。
    """
    global _pool, _checkpointer
    if _checkpointer is not None:
        return _checkpointer

    async with _init_lock:
        if _checkpointer is None:
            pool = await open_pool_with_retry()
            saver = AsyncPostgresSaver(conn=pool)
            # 官方要求：首次使用必须显式调用 setup()，它不是懒建的
            await saver.setup()
            _pool, _checkpointer = pool, saver

    return _checkpointer


async def get_checkpointer() -> AsyncPostgresSaver:
    """checkpointer 单例（FastAPI 依赖，正常由 lifespan 预热）"""
    if _checkpointer is None:
        await init_checkpointer()
    return _checkpointer


def get_pool() -> AsyncConnectionPool:
    """已建立的 psycopg 连接池"""
    if _pool is None:
        raise RuntimeError("PostgreSQL 连接池未初始化：应用 lifespan 未执行")
    return _pool


async def close_pool() -> None:
    """应用关闭时释放连接（幂等）"""
    global _pool, _checkpointer
    pool, _pool, _checkpointer = _pool, None, None
    if pool is not None:
        await pool.close()
