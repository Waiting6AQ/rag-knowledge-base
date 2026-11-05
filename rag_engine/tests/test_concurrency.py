"""并发闸门单元测试

只验证信号量的获取 / 释放 / 超时，不依赖真实 API 或事件循环之外的组件。
"""
import asyncio

import pytest
from fastapi import HTTPException

from core.concurrency import AsyncConcurrencyLimiter


def test_limits_concurrent_requests():
    """并发峰值不能超过 max_concurrent"""

    async def main():
        limiter = AsyncConcurrencyLimiter("测试", max_concurrent=2, wait_seconds=1)
        running = 0
        peak = 0

        async def worker():
            nonlocal running, peak
            async with limiter:
                running += 1
                peak = max(peak, running)
                await asyncio.sleep(0.02)
                running -= 1

        await asyncio.gather(*(worker() for _ in range(6)))
        return peak

    assert asyncio.run(main()) == 2


def test_timeout_returns_429():
    """满了且等不到位置 → 429"""

    async def main():
        limiter = AsyncConcurrencyLimiter("测试", max_concurrent=1, wait_seconds=0.01)
        await limiter.acquire()
        try:
            with pytest.raises(HTTPException) as exc:
                await limiter.acquire()
            return exc.value
        finally:
            limiter.release()

    exc = asyncio.run(main())
    assert exc.status_code == 429
    assert "请稍后再试" in exc.detail


def test_no_wait_mode_rejects_immediately():
    """wait_seconds=0：满了直接拒绝，不排队"""

    async def main():
        limiter = AsyncConcurrencyLimiter("测试", max_concurrent=1, wait_seconds=0)
        await limiter.acquire()
        try:
            with pytest.raises(HTTPException) as exc:
                await limiter.acquire()
            return exc.value
        finally:
            limiter.release()

    assert asyncio.run(main()).status_code == 429


def test_release_on_exception():
    """async with 里抛异常，许可也必须归还（否则下一次会一直等）"""

    async def main():
        limiter = AsyncConcurrencyLimiter("测试", max_concurrent=1, wait_seconds=0)
        with pytest.raises(RuntimeError):
            async with limiter:
                raise RuntimeError("boom")

        # 能再次拿到，说明上一次已经归还
        await limiter.acquire()
        limiter.release()
        return True

    assert asyncio.run(main()) is True


def test_waiter_enters_after_release():
    """排队的请求在许可释放后能进入"""

    async def main():
        limiter = AsyncConcurrencyLimiter("测试", max_concurrent=1, wait_seconds=1)
        await limiter.acquire()

        async def waiter():
            async with limiter:
                return "entered"

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.01)
        assert not task.done()      # 还没释放，应该一直等
        limiter.release()
        return await task

    assert asyncio.run(main()) == "entered"
