"""
嵌入模型适配器

将阿里云 DashScope Embedding API 封装为 LangChain 标准接口，
使得 Chroma、检索器等 LangChain 组件可以直接调用。
网络类异常（超时/服务不可用/请求失败）自动指数退避重试，
参数类错误（密钥、输入非法）直接抛出不重试。
"""
import time
from typing import List
from dashscope import TextEmbedding
from dashscope.common.error import (
    RequestFailure,
    ServiceUnavailableError,
    TimeoutException,
)
from langchain_core.embeddings import Embeddings

# 可重试异常：网络抖动/服务端临时故障，重试有意义
RETRYABLE_ERRORS = (TimeoutException, ServiceUnavailableError, RequestFailure)


class AliyunEmbeddings(Embeddings):
    """实现 LangChain Embeddings 接口，底层调用阿里云 TextEmbedding"""

    def __init__(self, model: str = "text-embedding-v4", max_retries: int = 3):
        self.model = model
        self.max_retries = max_retries

    def _call_with_retry(self, input_data):
        """指数退避重试：1s → 2s → 4s，重试耗尽后抛最后一次异常"""
        delay = 1
        for attempt in range(self.max_retries + 1):
            try:
                return TextEmbedding.call(model=self.model, input=input_data)
            except RETRYABLE_ERRORS:
                if attempt == self.max_retries:
                    raise
                time.sleep(delay)
                delay *= 2

    def embed_query(self, text: str) -> List[float]:
        """嵌入单条查询文本，返回一维向量"""
        # 暂不传 text_type：不同模型对该参数行为不一致，部分模型可能导致检索精度下降
        rsp = self._call_with_retry(text)
        if rsp.output is None or not rsp.output.get("embeddings"):
            raise RuntimeError(f"Embedding API 返回为空: {rsp}")
        return rsp.output["embeddings"][0]["embedding"]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """批量嵌入文档文本，返回二维向量列表"""
        batch_size = 20
        all_embeddings: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            rsp = self._call_with_retry(batch)
            if rsp.output is None or not rsp.output.get("embeddings"):
                raise RuntimeError(f"Embedding API 返回为空 (batch {i // batch_size}): {rsp}")
            all_embeddings.extend(emb["embedding"] for emb in rsp.output["embeddings"])
        return all_embeddings
