"""
CrossEncoder 重排序模型单例

为什么要单例：
- 模型加载是重活（几百 MB、几秒），每个请求各加载一次会把 CPU / 内存打满
- 原先是 `if not hasattr(self, "_reranker")` 的懒加载，并发首次请求会同时通过
  检查，8 个线程各加载一遍（压测日志里出现了 8 次 "Loading weights"）
- 用双重检查 + 线程锁保证全进程只加载一次

注意：这是同步的 CPU 推理，调用方应在事件循环之外执行
（当前由 LangGraph 的同步节点放进线程池）。
"""
import threading

from sentence_transformers import CrossEncoder

MODEL_NAME = "BAAI/bge-reranker-base"

_lock = threading.Lock()
_reranker: CrossEncoder | None = None


def get_reranker() -> CrossEncoder:
    """获取重排序模型单例（首次调用时加载，之后直接复用）

    lifespan 里会先调一次做预热，所以正常请求进来时模型已经就绪。
    """
    global _reranker
    if _reranker is None:
        with _lock:
            if _reranker is None:      # 等锁期间可能已被别的线程加载好
                _reranker = CrossEncoder(
                    MODEL_NAME,
                    model_kwargs={"torch_dtype": "auto"},
                )
    return _reranker
