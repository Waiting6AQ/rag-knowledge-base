"""BM25 中文分词的单元测试 + 回归测试

背景：BM25Retriever 默认按空格分词，中文句子会被整句切成一个 token，
索引侧和查询侧都对不上，BM25 那一路实际上没在工作。这里锁住修复。
"""
from services.bm25_index import Bm25IndexCache, tokenize_zh


# ==================== tokenize_zh 本身 ====================

def test_cjk_becomes_bigrams():
    assert tokenize_zh("测距仪") == ["测距", "距仪"]


def test_single_cjk_char_is_kept():
    """落单的汉字没有相邻字可组，保留单字而不是丢弃"""
    assert tokenize_zh("灯") == ["灯"]


def test_ascii_kept_whole_and_lowercased():
    """英文/数字整块保留（不切），便于型号、缩写精确匹配"""
    assert tokenize_zh("RAG") == ["rag"]
    assert tokenize_zh("E02") == ["e02"]


def test_mixed_script():
    assert tokenize_zh("CPU和E02错误") == ["cpu", "和", "e02", "错误"]


def test_punctuation_and_whitespace_dropped():
    assert tokenize_zh("蓝牙，测距。") == ["蓝牙", "测距"]
    assert tokenize_zh("  蓝牙\t测距\n") == ["蓝牙", "测距"]


def test_empty_input():
    assert tokenize_zh("") == []
    assert tokenize_zh("，。！") == []


# ==================== 回归：中文查询要能命中中文文档 ====================

class FakeVectorStore:
    def __init__(self, docs):
        self._docs = docs

    def get(self):
        return {
            "ids": [d[0] for d in self._docs],
            "documents": [d[1] for d in self._docs],
            "metadatas": [d[2] for d in self._docs],
        }


def make_cache():
    """构造 5 段互不重叠的文档，期望命中的排在正中间（下标 2）。

    位置是特意选的：分词失效时所有得分都是 0，rank_bm25 的 get_top_n 内部是
    np.argsort(scores)[::-1][:k]——全 0 时 argsort 给升序、再反转，于是退化成
    "返回最后 k 段"。期望文档放中间，才能让"没修好"和"修好了"两种结果的
    top-k 不同（放开头或结尾都会被这个退化顺序蒙对）。
    """
    docs = [
        ("id-0", "产品包装内含主机一台、说明书一份。", {"source": "a.md"}),
        ("id-1", "首次使用前请充满电，充电时指示灯为红色。", {"source": "b.md"}),
        ("id-2", "本产品提供一年整机保修服务。", {"source": "c.md"}),
        ("id-3", "如需发票请在订单备注中说明。", {"source": "d.md"}),
        ("id-4", "退换货需在签收后七日内申请。", {"source": "e.md"}),
    ]
    return Bm25IndexCache(FakeVectorStore(docs))


def test_chinese_query_hits_expected_doc():
    _, retriever = make_cache().ensure()
    retriever.k = 2

    hits = retriever.invoke("保修期是多久？")

    assert hits, "中文查询没命中任何文档，BM25 那一侧等于没工作"
    assert hits[0].metadata["source"] == "c.md"


def test_chinese_query_scores_are_not_all_zero():
    """分数全 0 说明查询词一个都没匹配上，此时返回的 top-k 与查询内容无关。

    这条直接断言机制本身，不依赖 top-k 的排序细节。
    """
    _, retriever = make_cache().ensure()

    scores = retriever.vectorizer.get_scores(tokenize_zh("保修期是多久？"))

    assert max(scores) > 0
    assert scores[2] == max(scores)
