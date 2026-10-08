"""
Qdrant 客户端与 collection 初始化

collection 用裸客户端建，不交给 langchain-qdrant：sparse 向量的 IDF 统计
（Modifier.IDF）只能在建 collection 时指定，而 QdrantVectorStore 的构造函数
不暴露这个参数，且建错了只能整个删库重建。建库逻辑集中在这一处。

检索分工（合起来是完整 BM25）：
  文档侧向量 = BM25 的 tf 长度归一化值（utils/sparse_embeddings.py）
  IDF        = Qdrant 按 Modifier.IDF 自动维护并在检索时乘上
"""
import asyncio

from qdrant_client import QdrantClient, models

from core.config import settings

# 命名向量：dense 走语义召回，sparse 走 BM25 关键词召回
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "text"
# DashScope text-embedding-v4 的输出维度；与建库时不一致会在构造向量库时报错
DENSE_SIZE = 1024
# 文档 ID 在 payload 里的路径：删除文档要按它过滤
DOC_ID_FIELD = "metadata.doc_id"

_client: QdrantClient | None = None


def get_qdrant_client() -> QdrantClient:
    """Qdrant 客户端单例

    用同步客户端：写入（document_service）和检索（rag_service 的检索节点）
    本来就在线程池里执行，用不上异步客户端。
    """
    global _client
    if _client is None:
        _client = QdrantClient(url=settings.QDRANT_URL)
    return _client


async def init_collection(name: str, attempts: int = 10, base_delay: float = 1.0) -> None:
    """确保 collection 和 payload 索引就绪（幂等），启动时调用

    连不上就让启动失败并打清楚的话，不要拖到首次请求才炸。
    compose 里靠 depends_on: service_healthy 保证顺序，这里的重试是给本地开发
    兜底——python main.py 时 Qdrant 容器可能还没起来。
    """
    client = get_qdrant_client()
    last_exc: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            _ensure(client, name)
            return
        except Exception as e:
            last_exc = e
            delay = min(base_delay * i, 5.0)
            print(f"⚠️ Qdrant 未就绪（{i}/{attempts}）: "
                  f"{type(e).__name__}: {e}；{delay:.1f}s 后重试")
            if i < attempts:
                await asyncio.sleep(delay)

    raise RuntimeError(f"Qdrant 在 {attempts} 次尝试后仍不可用") from last_exc


def _ensure(client: QdrantClient, name: str) -> None:
    if not client.collection_exists(name):
        client.create_collection(
            collection_name=name,
            vectors_config={
                DENSE_VECTOR_NAME: models.VectorParams(
                    size=DENSE_SIZE, distance=models.Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: models.SparseVectorParams(
                    modifier=models.Modifier.IDF,   # 建库后改不了
                ),
            },
        )

    # 删除文档要按 doc_id 过滤：有索引是索引查找，没索引得全量扫
    existing = client.get_collection(name).payload_schema or {}
    if DOC_ID_FIELD not in existing:
        client.create_payload_index(
            collection_name=name,
            field_name=DOC_ID_FIELD,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
