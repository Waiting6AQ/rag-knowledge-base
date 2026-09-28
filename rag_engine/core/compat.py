"""
平台兼容性修复

由 core/__init__.py 导入，因此任何 `from core.xxx import ...` 都会先执行它，
使用方不需要显式 import。
"""
import asyncio
import sys

# Windows 的 asyncio 默认策略是 ProactorEventLoop，而 psycopg 的异步模式不支持它
# （报错：Psycopg cannot use the 'ProactorEventLoop' to run in async mode）。
# 策略必须在【事件循环创建之前】切换，所以要在应用的最早期执行 —— 这就是
# 本模块挂在 core 包导入链上的原因。
# Linux 容器（Docker 部署）默认就是 SelectorEventLoop，不受这段影响。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    """给 uvicorn 用的事件循环工厂（仅 Windows 需要传）。

    上面的 set_event_loop_policy 对 uvicorn 无效：uvicorn 在 server.py 里把
    loop 工厂显式传给了 asyncio.Runner，而它的工厂在 win32 上硬编码返回
    ProactorEventLoop（见 uvicorn/loops/asyncio.py），绕过了 policy。
    启动时传 `loop="core.compat:selector_loop_factory"` 覆盖它。

    非 Windows 平台不要传 —— 传了会让 uvicorn 失去 uvloop。
    """
    return asyncio.SelectorEventLoop()
