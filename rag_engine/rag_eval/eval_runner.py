"""
RAG 评测脚本 — 离线跑 50 条标注问题，输出两个指标 + 按分类汇总

============================ 评测架构 ============================

文件：
  eval_questions.json  ← 50 条手动标注的测试问题（问题+期望来源+期望关键词+分类）
  eval_runner.py       ← 本文件：逐条跑 RAG 管线，打分，输出报告
  eval_report.json     ← 自动生成的完整评测报告

数据流：
  读取问题集 → 逐条调用 rag.chat() → 返回 answer + sources + confidence
    → check_source()   对比返回的 sources 和 expected_doc_source → 来源命中？
    → check_keywords() 在 answer 里搜索 expected_keywords         → 关键词覆盖？
    → 记录耗时
  → 按分类汇总 → 输出终端摘要 + eval_report.json

============================ 两个指标 ============================

[来源命中率] 测的是检索质量：期望的文档有没有出现在检索结果里
  → 对应行业标准的 Context Recall / Precision
  → 在 sources 列表里逐条比对 expected_doc_source 文件名字符串

[关键词命中率] 测的是回答质量：LLM 的回答有没有覆盖到关键信息
  → 对应行业标准的 Answer Relevance / Faithfulness 的简化版
  → 在 answer 字符串里用 Python 的 in 操作符逐词搜索（精确匹配，不区分大小写）
  → 局限：中文空格/同义词/表述差异会导致未命中，但回答内容可能完全正确

============================ 报告结构 ============================

eval_report.json 结构：
{
  "timestamp": "2026-06-25 10:32:44",
  "stats": {                       ← 汇总统计
    "total": 50,
    "categories": {                ← 按分类分组：置信度均值 + 关键词命中率均值
      "RAG基础": {"count": 3, "avg_confidence": 1.0, "avg_kw_hit_rate": 1.0},
      ...
    },
    "overall": {                   ← 全局指标
      "source_recall": "50/50 (100.0%)",
      "avg_keyword_hit_rate": "90.8%",
      "avg_confidence": 1.0,
      "rag_used": "50/50 (100%)",
      "total_time_seconds": 351.0,
      "avg_time_per_question": 7.02
    }
  },
  "results": [                     ← 每条问题的详细结果
    {
      "id": "Q01",
      "question": "什么是RAG？",
      "category": "RAG基础",
      "answer": "RAG（检索增强生成）是一种...",    ← LLM 完整回答
      "confidence": 1.0,
      "rag_used": true,
      "sources": [{"source": "RAG技术介绍.md", "index": 1}],
      "source_check": {"match": true, "expected": "RAG技术介绍.md", "found_sources": [...]},
      "keyword_check": {"hit_count": 4, "total": 4, "hit_rate": 1.0, "details": {...}},
      "time_seconds": 16.47
    },
    ...
  ]
}
"""
import asyncio
import json
import sys
import time
from pathlib import Path

# ======== 路径设置 ========
# rag_eval/ 已经在 rag_fastapi/ 下面，所以要导入 core.dependencies 只需要
# 把 rag_fastapi/（即 rag_eval/ 的父目录）加到 sys.path
_SELF_DIR = Path(__file__).resolve().parent   # → /rag_fastapi/rag_eval/
_RAG_DIR = _SELF_DIR.parent                   # → /rag_fastapi/
sys.path.insert(0, str(_RAG_DIR))

from core.dependencies import get_rag_service

QUESTIONS_FILE = _SELF_DIR / "eval_questions.json"   # 问题集
REPORT_FILE = _SELF_DIR / "eval_report.json"         # 输出报告

# ======================================================================
# 辅助函数
# ======================================================================

def load_questions():
    """从 JSON 文件读取问题集 → list[dict]"""
    with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def check_keywords(answer: str, keywords: list[str]) -> dict:
    """
    关键词命中检查 — 在 answer 里 Ctrl+F 搜每个关键词

    逻辑：answer.lower() 里有没有 keyword.lower() → 有就 True，没有就 False

    返回：
    {
      "hit_count": 3,           # 命中几个
      "total": 4,               # 总共几个
      "hit_rate": 0.75,         # 命中率
      "details": {              # 逐词详情
        "RAG": True,
        "检索": True,
        "幻觉": True,
        "prompt": False         ← 回答用中文"提示词"，没出现英文 prompt
      }
    }

    局限：纯字符串匹配。中文空格（"S 级" vs "S级"）、同义词（"指代" vs "代词"）、
         表述差异（"3元" vs "不到3元"）都会导致误判。
    """
    hits = {kw: kw.lower() in answer.lower() for kw in keywords}
    return {
        "hit_count": sum(hits.values()),
        "total": len(keywords),
        "hit_rate": sum(hits.values()) / len(keywords) if keywords else 0.0,
        "details": hits,
    }


def check_source(sources: list, expected_source: str | None) -> dict:
    """
    来源命中检查 — 期望的文档文件名有没有出现在检索结果里

    sources 是 RAG 管线返回的 SourceInfo 对象列表，每个有 .source 属性

    逻辑：遍历 sources，找有没有一个 .source 包含 expected_source（不区分大小写）

    返回：
    {
      "match": True,                               # 找到了
      "expected": "RAG技术介绍.md",                  # 期望的文件名
      "found_sources": ["RAG技术介绍.md", ...]       # 实际检索到的所有来源
    }
    如果 expected_source 是 None → match 返回 None（不计入统计）
    """
    if expected_source is None:
        return {"match": None, "reason": "未设置 expected_doc_source"}
    matched = any(expected_source.lower() in s.source.lower() for s in sources)
    return {
        "match": matched,
        "expected": expected_source,
        "found_sources": [s.source for s in sources],
    }


# ======================================================================
# 主评测逻辑
# ======================================================================

async def run_eval():
    """主函数：加载问题 → 逐条跑管线 → 打分 → 汇总 → 输出报告"""

    # ======== 第一步：加载问题集 ========
    questions = load_questions()
    print(f"📋 加载 {len(questions)} 条测试问题\n")

    # ======== 第二步：初始化 RAG 管线 ========
    # 不走 HTTP（不需要启动 FastAPI 服务），直接调用 RAGService.chat()
    # ChromaDB 数据在磁盘上，只要之前上传过文档就有
    rag = await get_rag_service()

    results = []      # 每条问题的详细结果
    stats = {         # 汇总统计（边跑边填）
        "total": len(questions),
        "categories": {},
        "overall": {},
    }

    start_total = time.time()

    # ======== 第三步：逐条问题跑管线 ========
    for i, q in enumerate(questions):
        print(f"[{i+1:02d}/{len(questions)}] {q['id']}: {q['question'][:50]}...", end=" ", flush=True)

        start = time.time()
        try:
            # 调 RAG 管线（非流式），conversation_id=None → 每条独立新对话
            response = await rag.chat(query=q["question"], conversation_id=None)
        except Exception as e:
            print(f"❌ 异常: {e}")
            results.append({"id": q["id"], "question": q["question"], "error": str(e)})
            continue

        elapsed = round(time.time() - start, 2)

        # --- 来源检查 ---
        # 答案正确 ≠ 检索正确。这里独立验证检索链路的输出
        source_result = check_source(response.sources, q.get("expected_doc_source"))

        # --- 关键词检查 ---
        # 检索正确 ≠ 答案覆盖了关键信息。这里独立验证 answer 的内容质量
        keyword_result = check_keywords(response.answer, q.get("expected_keywords", []))

        # --- 置信度 ---
        confidence = response.confidence if response.confidence is not None else 0.0

        # --- 组装本条结果 ---
        result = {
            "id": q["id"],
            "question": q["question"],
            "category": q.get("category", "未分类"),
            "answer": response.answer,                        # LLM 完整回答（存进报告供后续分析）
            "confidence": confidence,
            "rag_used": response.rag_used,                    # 是否使用了检索
            "sources": [{"source": s.source, "index": s.index} for s in response.sources],
            "source_check": source_result,                    # 来源检查详情
            "keyword_check": keyword_result,                  # 关键词检查详情
            "time_seconds": elapsed,                          # 单条耗时
        }
        results.append(result)

        # --- 终端打印本条摘要 ---
        # ✅ = 来源命中  ❌ = 来源未命中  ⬜ = 未设 expected_doc_source
        src_icon = "✅" if source_result["match"] else ("⬜" if source_result["match"] is None else "❌")
        kw_str = f"关键词 {keyword_result['hit_count']}/{keyword_result['total']}"
        print(f"置信度 {confidence:.0%} | {src_icon} | {kw_str} | {elapsed}s")

    # ======== 第四步：汇总统计 ========
    total_elapsed = round(time.time() - start_total, 1)

    # --- 来源命中率 ---
    # 只统计设了 expected_doc_source 的问题（match 不是 None 的）
    with_src = [r for r in results if r["source_check"].get("match") is not None]
    src_matches = sum(r["source_check"]["match"] for r in with_src)  # True=1, False=0
    stats["overall"]["source_recall"] = (
        f"{src_matches}/{len(with_src)} ({src_matches/len(with_src):.1%})"
        if with_src else "N/A"
    )

    # --- 关键词平均命中率 ---
    # 所有问题的 hit_rate 取算术平均（每条权重相等）
    kw_rates = [r["keyword_check"]["hit_rate"] for r in results if "keyword_check" in r]
    stats["overall"]["avg_keyword_hit_rate"] = (
        f"{sum(kw_rates)/len(kw_rates):.1%}" if kw_rates else "N/A"
    )

    # --- 平均置信度 ---
    conf_scores = [r["confidence"] for r in results if "confidence" in r]
    stats["overall"]["avg_confidence"] = (
        round(sum(conf_scores) / len(conf_scores), 3) if conf_scores else 0.0
    )

    # --- RAG 使用率 ---
    # 有多少问题实际使用了检索（检索到了文档）
    rag_used_count = sum(r.get("rag_used", False) for r in results)
    stats["overall"]["rag_used"] = f"{rag_used_count}/{len(results)} ({rag_used_count/len(results):.0%})"

    # --- 耗时 ---
    stats["overall"]["total_time_seconds"] = total_elapsed
    stats["overall"]["avg_time_per_question"] = round(total_elapsed / len(results), 2)

    # --- 按分类汇总 ---
    # 遍历所有结果，按 category 字段分组，分别统计置信度和关键词命中率
    for r in results:
        cat = r.get("category", "未分类")
        if cat not in stats["categories"]:
            stats["categories"][cat] = {"count": 0, "total_confidence": 0.0, "total_kw_rate": 0.0}
        stats["categories"][cat]["count"] += 1
        stats["categories"][cat]["total_confidence"] += r.get("confidence", 0.0)
        stats["categories"][cat]["total_kw_rate"] += r.get("keyword_check", {}).get("hit_rate", 0.0)

    # 算平均值
    for cat in stats["categories"]:
        c = stats["categories"][cat]
        c["avg_confidence"] = round(c["total_confidence"] / c["count"], 3)
        c["avg_kw_hit_rate"] = round(c["total_kw_rate"] / c["count"], 3)

    # ======== 第五步：输出报告 ========
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stats": stats,         # 汇总统计
        "results": results,     # 每条问题的完整结果（含 answer / sources / 评分详情）
    }

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # ======== 第六步：终端总结 ========
    print(f"\n{'='*60}")
    print(f"📊 评测完成 ({total_elapsed:.1f}s)")
    print(f"{'='*60}")
    print(f"  问题总数:         {stats['total']}")
    print(f"  来源召回率:       {stats['overall']['source_recall']}")
    print(f"  关键词平均命中率: {stats['overall']['avg_keyword_hit_rate']}")
    print(f"  平均置信度:       {stats['overall']['avg_confidence']:.1%}")
    print(f"  RAG 使用率:       {stats['overall']['rag_used']}")
    print(f"  平均耗时:         {stats['overall']['avg_time_per_question']}s/问")
    print(f"\n  按分类:")
    for cat, c in stats["categories"].items():
        print(f"    {cat}: {c['count']}条 | 置信度 {c['avg_confidence']:.1%} | 关键词 {c['avg_kw_hit_rate']:.1%}")
    print(f"\n  详细报告: {REPORT_FILE}")


if __name__ == "__main__":
    asyncio.run(run_eval())
