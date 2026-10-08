"""中文 BM25 稀疏向量的单元测试 + 回归测试

背景：默认的按空格分词对中文等于失效——整句会被切成一个 token，索引侧和
查询侧永远对不上，BM25 那一路实际上没在工作。这里锁住修复。
"""
from utils.sparse_embeddings import Bm25SparseEmbeddings, tokenize_zh


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


# ==================== 向量编码 ====================

def test_index_is_stable_across_instances():
    """同一个词的整数下标必须每次一样

    用内置 hash() 会带进程级随机盐，重启后下标全变、已入库的向量全部失配。
    """
    a = Bm25SparseEmbeddings().embed_query("保修期多久")
    b = Bm25SparseEmbeddings().embed_query("保修期多久")
    assert a.indices == b.indices


def test_document_indices_are_unique_and_sorted():
    """Qdrant 要求下标不重复；排序只是让输出稳定便于比对"""
    (vec,) = Bm25SparseEmbeddings().embed_documents(["保修保修服务"])
    assert len(vec.indices) == len(set(vec.indices))
    assert vec.indices == sorted(vec.indices)


def test_tf_saturates():
    """词频有饱和：出现两次的权重不到出现一次的两倍（BM25 的 k1 参数）"""
    emb = Bm25SparseEmbeddings()
    (once,) = emb.embed_documents(["保修"])
    (twice,) = emb.embed_documents(["保修保修"])
    idx = emb.embed_query("保修").indices[0]
    assert dict(zip(twice.indices, twice.values))[idx] < 2 * once.values[0]


def test_longer_document_downweights_matching_term():
    """同一个词出现在越长（越杂）的文档里，权重越低（BM25 的长度归一化）"""
    emb = Bm25SparseEmbeddings(avg_len=10)
    idx = emb.embed_query("保修").indices[0]
    (short,) = emb.embed_documents(["保修"])
    (long_,) = emb.embed_documents(["保修" + "无关内容" * 20])
    assert dict(zip(long_.indices, long_.values))[idx] < short.values[0]


# ==================== 回归：中文查询要能命中中文文档 ====================

def test_chinese_query_shares_terms_with_expected_doc():
    """中文查询的词要和中文文档的词对得上，且期望文档重合最多

    老实现（按空格分词）下中文整句塌成一个 token，查询和文档永远没有共同词，
    这一路等于没工作。这里直接断言"共同词的下标交集"——正是 Qdrant 算分的依据。
    """
    docs = [
        "产品包装内含主机一台、说明书一份。",
        "首次使用前请充满电，充电时指示灯为红色。",
        "本产品提供一年整机保修服务。",          # ← 期望命中（与原测试同一位置）
        "如需发票请在订单备注中说明。",
        "退换货需在签收后七日内申请。",
    ]
    emb = Bm25SparseEmbeddings()
    query_indices = set(emb.embed_query("保修期是多久？").indices)
    overlaps = [len(query_indices & set(v.indices)) for v in emb.embed_documents(docs)]

    assert max(overlaps) > 0, "中文查询和任何文档都没有共同词，sparse 那一路等于没工作"
    assert overlaps[2] == max(overlaps)
