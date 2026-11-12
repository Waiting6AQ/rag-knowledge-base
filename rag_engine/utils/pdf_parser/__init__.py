"""
PDF 结构化解析

面向带目录的产品说明书 / 技术手册：**按文档自己的章节结构切块，而不是按字数切**。
跨页表格在解析阶段拼回，每块都带章节路径和图片位置。

对外只有一个函数：
    docs = parse_pdf(path)
    if docs is None:          # 没有目录 / 解析失败 → 调用方降级到 PyPDFLoader
        ...
"""
import logging
from pathlib import Path

from langchain_core.documents import Document

from .chunker import collect_chunks, to_chunks

logger = logging.getLogger(__name__)


def parse_pdf(pdf_path: str) -> list[Document] | None:
    """解析带目录的 PDF，返回章节内容块

    返回 None 的情况（调用方必须准备降级路径）：
      - 前 15 页找不到目录：扫描件、论文、普通文档
      - 章节定位失败，或解析过程中抛异常：版面超出规则覆盖范围
    """
    try:
        raw = collect_chunks(pdf_path)
    except Exception as e:
        logger.warning("结构化解析失败（降级为普通 PDF 解析）: %s: %s", type(e).__name__, e)
        return None

    if not raw:
        logger.info("未检测到目录，按普通 PDF 解析")
        return None

    path = Path(pdf_path)
    chunks = to_chunks(raw, path.stem, path.name)
    if not chunks:
        logger.info("章节内没有可索引的内容，按普通 PDF 解析")
        return None

    logger.info("结构化解析完成: %d 个章节 → %d 个内容块", len(raw), len(chunks))
    return [Document(page_content=c["text"], metadata=c["metadata"]) for c in chunks]
