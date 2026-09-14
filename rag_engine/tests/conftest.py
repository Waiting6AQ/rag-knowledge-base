"""pytest 共用配置

1. 把引擎根目录加入模块搜索路径，使测试里可以直接 `from utils.xxx import ...`
2. 提供无 .env 也能跑测试的兜底（Settings 的 DASHSCOPE_API_KEY 为必填项）
"""
import os
import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

# 单元测试不访问真实 API：未配置 .env 时给一个占位值，避免 Settings 校验失败
os.environ.setdefault("DASHSCOPE_API_KEY", "test-placeholder-key")
