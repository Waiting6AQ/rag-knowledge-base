"""
链路 ID 中间件

Java 网关给每个请求分配 traceId，通过 X-Request-Id 传过来；直接打引擎（脚本、调试）时自己生成。
ID 存进 ContextVar，日志过滤器从里面取，引擎每条日志都带同一个 id；
同时写回响应头，前端报障时可以直接把这个 id 给过来。

用纯 ASGI 中间件而不是 BaseHTTPMiddleware：后者会把下游应用放进另一个任务、
每条 ASGI 消息（流式响应就是每个 token）都过一遍内存队列，
对 SSE 来说是白白多付的延迟，断开传播也更容易出问题。
这里只读写头，剩下的 send/receive 原样透传，对流的实时性零影响。
"""
import uuid

from core.logging import trace_id_var

HEADER = b"x-request-id"
MAX_LEN = 64


class TraceIdMiddleware:
    """读取/生成 X-Request-Id，放入 ContextVar 并回写到响应头"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # lifespan / websocket 不处理
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        trace_id = _read_header(scope) or uuid.uuid4().hex[:12]
        token = trace_id_var.set(trace_id)
        try:
            # send 包一层：响应开始时补上 X-Request-Id，其他消息原样转发
            await self.app(scope, receive, _with_header(send, trace_id))
        finally:
            # 请求结束还原，避免同一个任务上下文里残留上一个请求的 id
            trace_id_var.reset(token)


def _read_header(scope) -> str:
    """取 X-Request-Id；超过 64 字符的当作无效，别让客户端往日志里塞垃圾"""
    for key, value in scope.get("headers") or []:
        if key.lower() == HEADER:
            text = value.decode("latin-1").strip()
            return text if 0 < len(text) <= MAX_LEN else ""
    return ""


def _with_header(send, trace_id: str):
    async def wrapped(message):
        # ASGI 里只有 http.response.start 带响应头
        if message["type"] == "http.response.start":
            headers = list(message.get("headers") or [])
            headers.append((HEADER, trace_id.encode("latin-1")))
            message["headers"] = headers
        await send(message)

    return wrapped
