"""
并发闸门：限制同一时刻「在途」的请求数

和令牌桶的分工：
- 令牌桶管「每秒进来多少」（QPS）
- 信号量管「同一时刻有多少没处理完」（并发）

为什么放在引擎层：
网关已经挡了一层，但引擎可能被内部工具/测试脚本直接调用，
而且网关如果部署多个实例，限流是各算各的。引擎需要保护自己的
事件循环、线程池和上游 LLM 配额，所以保留最后一道闸门。

单进程有效：
uvicorn --workers N 时每个 worker 是独立进程，各有一份信号量，
集群级限流需要把计数放到 Redis。这里只做单实例保护。
"""
import asyncio

from fastapi import HTTPException


class AsyncConcurrencyLimiter:
    """asyncio 版的并发闸门

    用法：
        async with limiter:            # 非流式：进入时拿许可，退出时自动归还
            await do_work()

        await limiter.acquire()        # 流式：先拿许可……
        try:
            ...
        finally:
            limiter.release()          # ……在生成器结束时归还
    """

    def __init__(self, name: str, max_concurrent: int, wait_seconds: float):
        if max_concurrent <= 0:
            raise ValueError("max_concurrent 必须大于 0")
        self.name = name
        self._max = max_concurrent
        self._wait = max(wait_seconds, 0.0)
        # 不在 __init__ 里建 Semaphore：模块导入时可能还没有运行中的事件循环。
        # 延迟到第一次在协程里使用时创建（那时一定在 loop 里）。
        self._sem: asyncio.Semaphore | None = None

    def _semaphore(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(self._max)
        return self._sem

    async def acquire(self) -> None:
        """拿一个许可；排队超过 wait_seconds 抛 429

        429 必须在响应开始之前抛出，FastAPI 才能正常返回 JSON。
        流式接口要在构造 StreamingResponse 之前调用，不能等流开始后再拒绝。
        """
        sem = self._semaphore()
        if self._wait <= 0:
            # 不排队：满了直接拒绝
            if sem.locked():
                raise self._too_many()
            await sem.acquire()
            return
        try:
            await asyncio.wait_for(sem.acquire(), timeout=self._wait)
        except asyncio.TimeoutError:
            raise self._too_many() from None

    def release(self) -> None:
        """归还许可。

        所有路径都必须走到这里——正常结束、异常、客户端断开。漏还一次，
        这个位子就永久丢了，累积几次系统会「看起来没人但全满」。
        """
        if self._sem is not None:
            self._sem.release()

    async def __aenter__(self) -> "AsyncConcurrencyLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.release()

    def _too_many(self) -> HTTPException:
        return HTTPException(
            status_code=429,
            detail=f"当前请求较多（{self.name}），请稍后再试",
        )
