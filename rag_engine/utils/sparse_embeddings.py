"""
中文 BM25 稀疏向量（供 Qdrant 的 sparse vector 使用）

BM25 的分数 = tf 部分 × IDF。两边分工：
  这里：分词 → 稳定哈希映射成整数下标 → 算 tf 的长度归一化
  Qdrant：建 collection 时指定 Modifier.IDF，检索时自动维护并乘上文档频率统计

合起来是完整的 BM25。这样省掉了自己维护 df 表——难点在删除文档：要减回计数
就得额外存"每个文档出现过哪些词"，漏掉任何一条删除路径都会静默算错。
"""
import re
from collections import Counter
from hashlib import blake2b

from langchain_qdrant.sparse_embeddings import SparseEmbeddings, SparseVector


# 连续的 ASCII 字母数字算一块，连续的汉字算一块，标点和空白丢弃
_TOKEN_BLOCK = re.compile(r"[A-Za-z0-9]+|[一-鿿]+")


def tokenize_zh(text: str) -> list[str]:
    """中文按字符 bigram 切，英文/数字整块保留并转小写

    索引侧和查询侧必须共用同一套切法——BM25 打分靠"查询词和文档词一致"。

    按字符 bigram 而不是按词典分词：任意相邻两字都会进倒排表，查询里的任意
    两字组合都能命中，不依赖词典收录情况；产品型号、专有名词这类词典外的词
    同样能被切出来。
    """
    tokens: list[str] = []
    for block in _TOKEN_BLOCK.findall(text):
        if block[0].isascii():
            tokens.append(block.lower())
        elif len(block) == 1:
            tokens.append(block)          # 落单的汉字，没有相邻字可组
        else:
            tokens.extend(block[i:i + 2] for i in range(len(block) - 1))
    return tokens


class Bm25SparseEmbeddings(SparseEmbeddings):
    """中文文本 → Qdrant sparse 向量

    k1 / b 是 BM25 的标准参数（词频饱和速度、长度归一化强度），用默认值。
    avg_len 是语料平均文档长度，按 chunk 体量估即可：500 字左右的块经 bigram
    切分后约 500 个 token。它只影响长度归一化的相对强度，且融合用 RRF 只看
    排名不看分数，估偏了影响有限。
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75, avg_len: float = 500.0):
        self.k1 = k1
        self.b = b
        self.avg_len = avg_len

    @staticmethod
    def _index(token: str) -> int:
        """token → 32 位整数下标

        不能用内置 hash()：它带进程级随机盐，重启后同一个词会映射到不同下标，
        已入库的向量就全对不上了。blake2b 是确定性的。
        32 位空间下几千个词的碰撞概率可以忽略，真撞了也只是两个词的分数合并。
        """
        digest = blake2b(token.encode("utf-8"), digest_size=4).digest()
        return int.from_bytes(digest, "big")

    def _tf_values(self, text: str) -> dict[int, float]:
        """文档侧：算 tf 的长度归一化值（IDF 那一半由 Qdrant 乘）"""
        tokens = tokenize_zh(text)
        if not tokens:
            return {}
        # 先按下标合并词频：不同的词万一撞到同一下标，词频要相加而不是互相覆盖
        merged: dict[int, int] = {}
        for token, tf in Counter(tokens).items():
            idx = self._index(token)
            merged[idx] = merged.get(idx, 0) + tf
        denom = self.k1 * (1 - self.b + self.b * len(tokens) / self.avg_len)
        return {idx: tf * (self.k1 + 1) / (tf + denom) for idx, tf in merged.items()}

    def embed_documents(self, texts: list[str]) -> list[SparseVector]:
        """文档侧：tf 的归一化值（同一个词在文中出现越多权重越高，长文归一化）"""
        vectors = []
        for text in texts:
            pairs = sorted(self._tf_values(text).items())
            vectors.append(SparseVector(
                indices=[idx for idx, _ in pairs],
                values=[val for _, val in pairs],
            ))
        return vectors

    def embed_query(self, text: str) -> SparseVector:
        """查询侧：只标"哪些词出现过"，全部权重 1.0，IDF 由 Qdrant 统一乘上"""
        indices = sorted({self._index(tok) for tok in tokenize_zh(text)})
        return SparseVector(indices=indices, values=[1.0] * len(indices))
