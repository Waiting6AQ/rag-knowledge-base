"""
日志配置

统一入口：控制台 + 滚动文件（UTF-8）。
级别由环境变量 LOG_LEVEL 控制，默认 INFO。

用法：应用入口调用一次 setup_logging()，其他模块直接
    logger = logging.getLogger(__name__)
    logger.info(...)
"""
import logging
import logging.handlers
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "engine.log"

_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging() -> None:
    """初始化根日志（幂等，重复调用不会叠加 handler）"""
    global _configured
    if _configured:
        return
    _configured = True

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    level = os.getenv("LOG_LEVEL", "INFO").upper()

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)

    # 单文件 10MB，保留 5 份（最多 50MB），不会无限增长
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

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
