# core 包

# 平台兼容修复（Windows 事件循环策略）必须尽早生效。挂在这里是为了让任何
# `from core.xxx import ...` 都先执行它，免得每个模块各自记得 import 一次。
from core import compat  # noqa: F401
