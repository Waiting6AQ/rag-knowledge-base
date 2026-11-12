"""
PDF 切分方式 A/B 评测

对比两种切分的检索命中率：
  旧：PyPDFLoader 按页加载 + RecursiveCharacterTextSplitter 固定长度切分
  新：结构化解析，按章节切分

两种检索模式：
  hybrid（默认）= 和生产完全一致：Qdrant dense+sparse 双路召回 + 服务端 RRF + CrossEncoder 精排
  dense        = 只做向量检索。变量更干净，适合解释"差距是不是切分带来的"

hybrid 模式会建两个临时 collection，跑完自动删掉，不碰线上的 rag_documents。

旧块没有章节信息，用 20 字片段的重叠把它归到最接近的新块所在章节，
保证两边的判据是同一套。

用法：
    python rag_eval/chunk_ab_test.py [PDF路径] [--mode hybrid|dense]
输出：
    终端对比表 + rag_eval/chunk_ab_report.{mode}.json
"""
import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 把 rag_engine/（rag_eval 的父目录）加进 sys.path，保证能 import core / utils
_RAG_DIR = str(Path(__file__).resolve().parent.parent)
if _RAG_DIR not in sys.path:
    sys.path.insert(0, _RAG_DIR)

from core.config import settings                 # noqa: E402
from core.qdrant import (                        # noqa: E402
    DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME, get_qdrant_client, init_collection,
)
from core.reranker import get_reranker           # noqa: E402
from utils.embeddings import AliyunEmbeddings    # noqa: E402
from utils.pdf_parser import parse_pdf           # noqa: E402
from utils.sparse_embeddings import Bm25SparseEmbeddings   # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_PDF = Path(r"D:\workspace\rag_project\pdf_chunk_exp\table_manual_samples\RTS-700.pdf")
QUESTIONS_FILE = EVAL_DIR / "manual_questions.json"

SHINGLE = 20        # 旧块归章节时用的片段长度
TOP_K = settings.TOP_K          # 生产配置：混合检索先取 5 条
RERANK_THRESHOLD = 0.3          # 与 rag_service._rerank 保持一致
TOP_N = 3                       # 只评估前 3 名（精排后交给模型的块数）


def chapter_of(doc) -> str | None:
    """新块的章节号：取 path 最后一项的编号"""
    path = doc.metadata.get("path") or []
    return path[-1].split(" ", 1)[0] if path else None


def shingles(text: str) -> set[str]:
    return {text[i:i + SHINGLE] for i in range(len(text) - SHINGLE + 1)}


def assign_old_chapters(old_chunks, new_chunks) -> list[str | None]:
    """把旧块归到章节：它落进哪一章的片段最多，就归那一章

    这是"事后标注"，只用于让两边可比——生产环境的旧块本来就没有章节信息。
    """
    owner: dict[str, str] = {}
    for doc in new_chunks:
        ch = chapter_of(doc)
        if not ch:
            continue
        for sh in shingles(doc.page_content):
            owner.setdefault(sh, ch)

    result = []
    for doc in old_chunks:
        counter = Counter(owner[sh] for sh in shingles(doc.page_content) if sh in owner)
        result.append(counter.most_common(1)[0][0] if counter else None)
    return result


def build_chunks(pdf: Path):
    new_chunks = parse_pdf(str(pdf))
    if not new_chunks:
        raise SystemExit("结构化解析失败，无法对比")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""],
    )
    old_chunks = splitter.split_documents(PyPDFLoader(str(pdf)).load())

    new_ch = [chapter_of(d) for d in new_chunks]
    old_ch = assign_old_chapters(old_chunks, new_chunks)
    return new_chunks, old_chunks, new_ch, old_ch


# ==================== dense：纯向量 ====================

def rank_in(chapters: list[str | None], expected: str) -> int | None:
    for rank, ch in enumerate(chapters[:TOP_N], start=1):
        if ch == expected:
            return rank
    return None


def eval_dense(questions, new_chunks, old_chunks, new_ch, old_ch):
    emb = AliyunEmbeddings(model=settings.EMBEDDING_MODEL_NAME)
    print("正在嵌入内容块 ...")
    new_vecs = np.asarray(emb.embed_documents([d.page_content for d in new_chunks]), dtype=np.float32)
    old_vecs = np.asarray(emb.embed_documents([d.page_content for d in old_chunks]), dtype=np.float32)

    def top_idx(qv, mat):
        q = np.asarray(qv, dtype=np.float32)
        sims = mat @ (q / (np.linalg.norm(q) + 1e-9))
        return np.argsort(-sims)[:TOP_N].tolist()

    rows = []
    for q in questions:
        qv = emb.embed_query(q["question"])
        old_chapters = [old_ch[i] for i in top_idx(qv, old_vecs)]
        new_chapters = [new_ch[i] for i in top_idx(qv, new_vecs)]
        rows.append(_row(q, old_chapters, new_chapters))
    return rows


# ==================== hybrid：和生产一致 ====================

def _build_store(collection: str):
    from langchain_qdrant import QdrantVectorStore, RetrievalMode

    return QdrantVectorStore(
        client=get_qdrant_client(),
        collection_name=collection,
        embedding=AliyunEmbeddings(model=settings.EMBEDDING_MODEL_NAME),
        retrieval_mode=RetrievalMode.HYBRID,
        sparse_embedding=Bm25SparseEmbeddings(avg_len=settings.CHUNK_SIZE),
        vector_name=DENSE_VECTOR_NAME,
        sparse_vector_name=SPARSE_VECTOR_NAME,
    )


def _prepare_collection(name: str, chunks, chapters) -> None:
    client = get_qdrant_client()
    client.delete_collection(name)          # 清掉上次中断留下的
    asyncio.run(init_collection(name))
    for doc, ch in zip(chunks, chapters):
        doc.metadata["chapter"] = ch or ""
    _build_store(name).add_documents(chunks)
    print(f"  {name}: 写入 {len(chunks)} 块")


def _search_and_rerank(store, question: str) -> list[str]:
    """混合检索取 TOP_K → 精排 → 保留 ≥0.3，返回按名次排好的章节号"""
    docs = store.similarity_search(question, k=TOP_K)
    if len(docs) > 1:
        reranker = get_reranker()
        scores = reranker.predict([(question, d.page_content) for d in docs])
        ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
        docs = [d for d, s in ranked if s >= RERANK_THRESHOLD]
    return [d.metadata.get("chapter") or None for d in docs]


def eval_hybrid(questions, new_chunks, old_chunks, new_ch, old_ch):
    old_name, new_name = "ab_test_old", "ab_test_new"
    print("写入临时 collection（hybrid: dense + BM25）...")
    _prepare_collection(old_name, old_chunks, old_ch)
    _prepare_collection(new_name, new_chunks, new_ch)

    try:
        old_store, new_store = _build_store(old_name), _build_store(new_name)
        rows = []
        for q in questions:
            rows.append(_row(q, _search_and_rerank(old_store, q["question"]),
                             _search_and_rerank(new_store, q["question"])))
        return rows
    finally:
        client = get_qdrant_client()
        for name in (old_name, new_name):
            try:
                client.delete_collection(name)
            except Exception:
                pass


def _row(q: dict, old_chapters: list, new_chapters: list) -> dict:
    return {
        "id": q["id"],
        "question": q["question"],
        "expected": q["expected_chapter"],
        "old_rank": rank_in(old_chapters, q["expected_chapter"]),
        "new_rank": rank_in(new_chapters, q["expected_chapter"]),
        "old_top1": old_chapters[0] if old_chapters else None,
        "new_top1": new_chapters[0] if new_chapters else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", nargs="?", default=str(DEFAULT_PDF))
    parser.add_argument("--mode", choices=["hybrid", "dense"], default="hybrid")
    args = parser.parse_args()

    questions = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    pdf = Path(args.pdf)
    print(f"PDF: {pdf.name} | 模式: {args.mode}")

    new_chunks, old_chunks, new_ch, old_ch = build_chunks(pdf)
    unassigned = sum(1 for c in old_ch if c is None)
    print(f"新块 {len(new_chunks)} 个 | 旧块 {len(old_chunks)} 个（{unassigned} 个归不到章节）")

    if args.mode == "hybrid":
        rows = eval_hybrid(questions, new_chunks, old_chunks, new_ch, old_ch)
    else:
        rows = eval_dense(questions, new_chunks, old_chunks, new_ch, old_ch)

    def mark(rank: int | None) -> str:
        return f"#{rank}" if rank else "-"

    for r in rows:
        print(f"{r['id']}  期望 {r['expected']:<6} 旧 {mark(r['old_rank']):<4} 新 {mark(r['new_rank']):<4} {r['question']}")

    def hits(key: str, k: int) -> int:
        return sum(1 for r in rows if r[key] and r[key] <= k)

    n = len(rows)
    summary = {
        "mode": args.mode,
        "questions": n,
        "chunks": {"old": len(old_chunks), "new": len(new_chunks)},
        "top1": {"old": hits("old_rank", 1), "new": hits("new_rank", 1)},
        "top3": {"old": hits("old_rank", 3), "new": hits("new_rank", 3)},
    }
    print()
    print(f"top-1 命中:  旧 {hits('old_rank', 1)}/{n}   新 {hits('new_rank', 1)}/{n}")
    print(f"top-3 命中:  旧 {hits('old_rank', 3)}/{n}   新 {hits('new_rank', 3)}/{n}")

    report = EVAL_DIR / f"chunk_ab_report.{args.mode}.json"
    report.write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n报告已写入: {report}")


if __name__ == "__main__":
    main()
