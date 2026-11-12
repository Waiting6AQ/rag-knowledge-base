"""
把章节结构切成检索用的内容块

从实验的 export_chunks.py 抽出来，只保留"切块"这一件事：
去掉了 CLI、Markdown 输出和写文件，改成返回可直接转成 Document 的结构。

三步处理：
  ① 过滤空块 —— 只有标题、内容全在子标题下的章节不进索引
  ② 章节路径拼在正文最前面 —— 上级标题的关键词也能被检索到
  ③ 超长章节按段落切、表格按数量分组 —— 避免一块里塞进十几个不相关的表
"""
import pdfplumber

from .build_chunks import (
    build_stack, table_boxes, collect_bodies, tables_in_range,
    collect_images, chapter_path,
)
from .locate_chapters import locate_chapters
from .merge_cross_page import (
    collect_tables, build_chains, merge_chain, unique_headers, row_to_text,
)
from .parse_toc import find_toc_pages

# 单个 chunk 的字符上限，超过就按段落贪心打包
MAX_CHARS = 1200

# 一个 chunk 里最多放几个表格。实测同一节里挤 7 个表会变成 3400+ 字符、
# 语义很杂（语言设置、触发键、单位设置混在一起），检索命中后模型要在一堆
# 不相关的表里找，效果差。按【表格链】分组，跨页的表已经合并成一条链，不会切坏。
MAX_TABLES_PER_CHUNK = 2

# 目录页只在前 N 页里找（说明书/手册的目录都在开头）
TOC_SCAN_PAGES = 15


def collect_chunks(pdf_path: str) -> list[dict] | None:
    """跑完整流程，返回每个章节的原始内容

    找不到目录时返回 None —— 那是"这份文档不适合结构化解析"的信号，
    由调用方降级到普通 PDF 加载器，这里不抛异常也不兜底内容。
    """
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)

        toc_pages = find_toc_pages(pdf, TOC_SCAN_PAGES)
        if not toc_pages:
            return None

        chapters = [e for _, entries in toc_pages for e in entries]
        last_toc = max(p for p, _ in toc_pages)
        located = locate_chapters(pdf, chapters, start_page=last_toc + 1)
        if not located:
            return None
        stacks = build_stack(located)

        # 表格先行：跨页的在 build_chains 里就拼回一条链，后面按范围分给各章节
        chains = build_chains(collect_tables(pdf, 1, total))
        boxes = table_boxes(chains)

        # 逐章收集正文 / 表格 / 插图；下一章的起点就是本章的终点
        raw = []
        for i, ch in enumerate(located):
            nxt = located[i + 1] if i + 1 < len(located) else None
            start = (ch["found_page"], ch["top"])
            end = (nxt["found_page"], nxt["top"]) if nxt else None
            raw.append({
                "ch": ch,
                "path": chapter_path(stacks[i]),
                "stack": stacks[i],
                "bodies": collect_bodies(pdf, ch, nxt, boxes, total),
                "tables": tables_in_range(chains, start, end),
                "images": collect_images(pdf, ch, nxt, boxes, total),
            })
        return raw


def pack_paragraphs(paragraphs: list[str], max_chars: int) -> list[list[str]]:
    """把段落贪心打包成若干组，每组不超过 max_chars

    贪心 = 能塞进当前组就塞，塞不下就开新组：尊重段落边界，不从句子中间切开。
    """
    groups: list[list[str]] = []
    cur: list[str] = []
    size = 0

    for p in paragraphs:
        if cur and size + len(p) > max_chars:
            groups.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += len(p)

    if cur:
        groups.append(cur)
    return groups or [[]]


def table_to_lines(chain: list[dict]) -> list[str]:
    """把一个表格链转成"每行带列名"的文本行"""
    header, body = merge_chain(chain)
    if not body:
        return []
    show_header = unique_headers(header)
    lines = ["[表格]"]
    lines += [row_to_text(show_header, r) for r in body]
    return lines


def split_tables(tables: list, max_per_group: int = MAX_TABLES_PER_CHUNK) -> list[list]:
    """按"每组最多 N 个表格链"分组；传进来的是链，所以不会把一张表切开"""
    if not tables:
        return [[]]
    return [tables[i:i + max_per_group] for i in range(0, len(tables), max_per_group)]


def build_text(path: str, bodies: list[str], tables: list, suffix: str = "") -> str:
    """拼出检索用的文本：章节路径 + 正文 + 表格"""
    parts = [f"【{path}{suffix}】"]
    parts.extend(bodies)
    for chain in tables:
        parts.extend(table_to_lines(chain))
    return "\n".join(parts)


def to_chunks(raw: list[dict], doc_name: str, source: str) -> list[dict]:
    """把原始章节内容转成最终的内容块

    metadata 只留检索和溯源要用的：
        source  文件原名
        path    章节路径（浅层 → 深层）
        page    章节起始页（1 起始）
        images  图片位置，留给"回答时渲染原图"用；不接图片时也不占多少空间
    """
    out = []
    for c in raw:
        bodies, tables, images = c["bodies"], c["tables"], c["images"]

        # 只有标题的章节跳过：进索引只会挤占检索结果
        if not bodies and not tables and not images:
            continue

        # 正文按长度切、表格按数量分组，块数取两者较大值
        body_groups = pack_paragraphs(bodies, MAX_CHARS) if bodies else [[]]
        table_groups = split_tables(tables)
        n_blocks = max(len(body_groups), len(table_groups))

        for gi in range(n_blocks):
            body_part = body_groups[gi] if gi < len(body_groups) else []
            table_part = table_groups[gi] if gi < len(table_groups) else []
            is_last = gi == n_blocks - 1
            suffix = f"（{gi + 1}/{n_blocks}）" if n_blocks > 1 else ""

            out.append({
                "id": f"{doc_name}-{c['ch']['number']}"
                      + (f"-{gi + 1}" if n_blocks > 1 else ""),
                "text": build_text(c["path"], body_part, table_part, suffix),
                "metadata": {
                    "source": source,
                    "path": [s["number"] + " " + s["title"] for s in c["stack"]],
                    "page": c["ch"]["found_page"],
                    # 图片位置挂在章节的最后一块上：图在章节里位置不固定，
                    # 放最后一块能保证整节被检索命中时至少有一块带着它
                    "images": images if is_last else [],
                },
            })
    return out
