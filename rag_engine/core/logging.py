"""
日志配置

统一入口：控制台 + 滚动文件（UTF-8）。
级别由环境变量 LOG_LEVEL 控制，默认 INFO。

用法：应用入口调用一次 setup_logging()，其他模块直接
    logger = logging.getLogger(__name__)
    logger.info(...)
"""
import contextvars
import logging
import logging.handlers
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "engine.log"

_FORMAT = "%(asctime)s %(levelname)-7s [%(trace_id)s] [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 链路 ID：由 core/trace.py 的中间件按请求写入（ContextVar，异步任务之间互不干扰）
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")

_configured = False


class _TraceIdFilter(logging.Filter):
    """把当前请求的 traceId 塞进每条日志记录，格式里用 %(trace_id)s 输出

    挂在 handler 上而不是 logger 上：子 logger 的记录是"传播"上来的，
    logger 级的 filter 管不到，只有 handler 级能覆盖全部日志。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_var.get()
        return True


class _ColorFormatter(logging.Formatter):
    """控制台专用：级别按严重程度上色；文件仍用不带色的 Formatter"""

    COLORS = {
        logging.DEBUG: "\033[2m",        # 暗色
        logging.INFO: "\033[32m",        # 绿
        logging.WARNING: "\033[33m",     # 黄
        logging.ERROR: "\033[31m",       # 红
        logging.CRITICAL: "\033[1;31m",  # 粗红
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        color = self.COLORS.get(record.levelno)
        if color:
            # 格式串里级别字段在前，第一次出现的就是它
            line = line.replace(record.levelname, f"{color}{record.levelname}{self.RESET}", 1)
        return line


def setup_logging() -> None:
    """初始化根日志（幂等，重复调用不会叠加 handler）"""
    global _configured
    if _configured:
        return
    _configured = True

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    level = os.getenv("LOG_LEVEL", "INFO").upper()

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)
    trace_filter = _TraceIdFilter()

    console = logging.StreamHandler(sys.stdout)
    # 只有终端才上色：输出被重定向（写文件、Docker 无 tty、CI）时自动退回纯文本
    console.setFormatter(
        _ColorFormatter(_FORMAT, datefmt=_DATE_FORMAT) if sys.stdout.isatty() else formatter
    )
    console.addFilter(trace_filter)

    # 单文件 10MB，保留 5 份（最多 50MB），不会无限增长
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(trace_filter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(file_handler)

    # 第三方库的 INFO 太吵：每次模型 / MCP 调用都会打一行 HTTP 200。
    # 压到 WARNING，只保留连接失败这类真正需要关注的事件。
    for name in ("httpx", "httpx2", "httpcore", "urllib3", "langchain_openai"):
        logging.getLogger(name).setLevel(logging.WARNING)

    # 热重载器会监控整个项目目录，而日志文件每写一行就算一次"变化"，
    # 不压掉的话会形成"写日志 → 变化 → 再写日志"的刷屏循环
    for name in ("watchfiles", "watchfiles.main"):
        logging.getLogger(name).setLevel(logging.WARNING)
