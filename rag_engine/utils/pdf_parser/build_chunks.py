"""
按章节把内容打包成块

============================ 这一步在做什么 ============================

前两步已经拿到：
    · 表格数据（跨页合并 + 图示标记）      ← merge_cross_page.py
    · 章节位置（每章在页面上的精确起点）    ← locate_chapters.py

这一步把它们拼起来：

    对每个章节，收集它范围内的【正文段落】和【表格】，打包成一个块。

        章节 A 的起点  →  章节 B 的起点
        ↑ 这个区间里的所有内容，都属于章节 A

============================ 两个关键处理 ============================

① 【正文要排除表格区域】

    表格里的文字也会被 extract_text_lines() 提取出来，但它们已经由
    表格逻辑单独处理过了（结构化 + 跨页合并 + 图示标记），不能再算一遍。
    所以按坐标判断：落在表格 bbox 内的文字行，不算正文。

② 【表格按起点归属】

    一个跨页表格可能横跨两页，它属于哪一章？
    按它的【起始位置】算 —— 从哪一页哪个位置开始，就属于包含那个位置的章节。

============================ 输出 ============================

先打印结构供人工核对（每章的路径、正文行数、表格数、内容预览）。
确认结构对了，再考虑输出成 JSON / Markdown 之类的格式。

用法：
    python build_chunks.py <PDF路径>

依赖：
    pip install pdfplumber
"""
import re
import sys
from pathlib import Path

import pdfplumber

from .merge_cross_page import (
    collect_tables, build_chains, merge_chain, unique_headers, row_to_text,
    graphics_in,
)
from .parse_toc import find_toc_pages, find_pdf_page_of
from .locate_chapters import locate_chapters, line_matches_title

# 页眉区域：这个高度以内的文字不算正文
HEADER_ZONE = 70

# 页码行的特征：纯数字，或 "- 4 -" / "— 12 —" 这种
PAGE_NO_PATTERN = re.compile(r"^[\s\-—–_]*\d{1,4}[\s\-—–_]*$")

# 判定"页面下部"的比例阈值
FOOTER_RATIO = 0.7


def is_page_footer(text: str, top: float, page_height: float) -> bool:
    """判断这一行是不是页脚页码

    不能只看位置 —— 实测这份文档的页脚在 top=678（页高 842），
    只到页面的 80% 处，离页底还有 160 多点，
    用"距页底 N 点内"这种固定阈值会漏掉它。

    所以【位置 + 内容模式】两个条件一起判断：
      · 位置在页面下部（70% 以下）
      · 内容长得像页码（"- 4 -" / "12"）
    """
    if top < page_height * FOOTER_RATIO:
        return False
    return bool(PAGE_NO_PATTERN.match(text.strip()))


def chapter_path(stack: list[dict]) -> str:
    """把章节栈拼成可读路径，如 "1.3 鍵盤及觸摸屏 > 1.3.1 鍵盤" """
    return " > ".join(f"{c['number']} {c['title']}" for c in stack)


def build_stack(chapters: list[dict]) -> list[list[dict]]:
    """给每个章节算出它的【完整层级路径】

    比如 1.3.1 的路径是 [1, 1.3, 1.3.1] ——
    靠"层级"维护一个栈：遇到新章节，把栈里"同级及更深"的弹掉，再压入。
    """
    stacks: list[list[dict]] = []
    stack: list[dict] = []
    for ch in chapters:
        while stack and stack[-1]["level"] >= ch["level"]:
            stack.pop()
        stack.append(ch)
        stacks.append(list(stack))
    return stacks


def table_boxes(chains: list[list[dict]]) -> list[dict]:
    """把表格链拆成"每个表格段的位置"，供判断正文行是否落在表格里

    合并后的链可能有多段（跨页），每段都有自己的位置，所以逐段记录。
    """
    boxes = []
    for chain in chains:
        for seg in chain:
            sig = seg["sig"]
            boxes.append({
                "page": seg["page"],
                "x0": sig["x0"], "top": sig["top"],
                "x1": sig["x1"], "bottom": sig["bottom"],
                "chain": chain,
            })
    return boxes


def line_in_any_table(page_no: int, top: float, boxes: list[dict]) -> bool:
    """这一行是不是落在某个表格的区域里"""
    for b in boxes:
        if b["page"] == page_no and b["top"] - 2 <= top <= b["bottom"] + 2:
            return True
    return False


def pos_lt(a: tuple, b: tuple) -> bool:
    """位置比较：(页码, top) 元组比大小"""
    return a[0] < b[0] or (a[0] == b[0] and a[1] < b[1])


def collect_bodies(pdf, ch: dict, nxt: dict | None, boxes: list[dict],
                   total_pages: int) -> list[str]:
    """收集某个章节范围内的【正文行】"""
    start = (ch["found_page"], ch["top"])
    end = (nxt["found_page"], nxt["top"]) if nxt else None

    last_page = nxt["found_page"] if nxt else total_pages
    lines = []

    for page_no in range(ch["found_page"], last_page + 1):
        page = pdf.pages[page_no - 1]
        for line in page.extract_text_lines():
            text = (line.get("text") or "").strip()
            if not text:
                continue

            pos = (page_no, line["top"])
            if not pos_lt(start, pos):          # 在起点之前
                continue
            if end and not pos_lt(pos, end):    # 到了下一章
                break

            # 跳过页眉（页面顶部区域）
            if line["top"] < HEADER_ZONE:
                continue
            # 跳过页脚页码（位置 + 内容模式双重判断）
            if is_page_footer(text, line["top"], page.height):
                continue
            # 跳过标题行本身（标题单独展示，混在正文里重复）
            if line_matches_title(text, ch["number"], ch["title"]):
                continue
            # 跳过表格区域内的文字（由表格逻辑单独处理）
            if line_in_any_table(page_no, line["top"], boxes):
                continue

            lines.append(text)

    return lines


# 图形对象向外扩多少点 —— 用来把图周围的【标注文字】圈进来
LABEL_MARGIN = 60

# 判定"标注"的最大字数 —— 超过这个长度的行算【正文】，不并进图片范围
#
# 为什么要区分：实测两类图的处理方式不一样
#   · 仪器部件图：标注是"手柄""物鏡"这样的【短词】，分布在图四周 → 要包含
#   · 键盘图：按键标签画在图【内部】，图本身就完整；
#             图上方是"儀器的操作指令、資料登錄通過鍵盤…"这样的【长句正文】→ 不能包含
# 所以按行看字数：短行 = 标注，长行 = 正文。
LABEL_MAX_CHARS = 12


def expand_to_include_labels(page, g_bbox: tuple, margin: float = LABEL_MARGIN) -> list:
    """把图形的 bbox 扩展成"图 + 周围标注"的完整范围

    ==================== 为什么需要 ====================

    PDF 里"图"和"图上的标注"是【分开的对象】——
    标注（"手柄"、"物鏡"…）是独立的文本对象，位置在图形 bbox 的【外面】。
    只按图形 bbox 渲染，标注会被整条裁掉。

    ==================== 但不能无脑扩 ====================

    实测两类图的情况【完全相反】：

        · 仪器部件图：标注是【短词】，散布在图的四周   →  要包含
        · 键盘图    ：按键标签画在图【内部】，图本身完整；
                      图上方是整段【正文】             →  不能包含

    所以按【行】判断字数：短行（≤ LABEL_MAX_CHARS）= 标注，长行 = 正文。
    """
    x0, top, x1, bottom = g_bbox

    # 判断基准固定为"图形 bbox + margin"。
    # 【关键】它不能被下面的扩边结果改写 —— 否则会滚雪球：
    #   包含一段文字 → 边界变大 → 又碰到下一段 → 再变大……
    #   实测键盘图最后把正文、标题、表格全框进来了，一路扩到整页。
    bx0, btop = max(0, x0 - margin), max(0, top - margin)
    bx1, bbottom = min(page.width, x1 + margin), min(page.height, bottom + margin)

    # 结果的起点是【原图 bbox】而不是"图 + margin" ——
    # 这样周围没有标注的图（比如键盘图，标签都画在图内部）就保持原始大小，
    # 不会白白多出一圈空白。只有真的找到标注时，下面的循环才会扩大它。
    ex0, etop, ex1, ebottom = x0, top, x1, bottom

    for line in page.extract_text_lines():
        text = (line.get("text") or "").strip()
        # 长行 = 正文，不并进来
        if not text or len(text) > LABEL_MAX_CHARS:
            continue

        chars = line.get("chars") or []
        if not chars:
            continue
        lx0 = min(c["x0"] for c in chars)
        lx1 = max(c["x1"] for c in chars)
        ltop = min(c["top"] for c in chars)
        lbottom = max(c["bottom"] for c in chars)

        # 和"图形 + margin"有重叠就并进来。
        # （用"有重叠"而不是"中心点在范围内" —— 后者会把边缘的标注切成一半）
        if lx1 > bx0 and lx0 < bx1 and lbottom > btop and ltop < bbottom:
            ex0, etop = min(ex0, lx0), min(etop, ltop)
            ex1, ebottom = max(ex1, lx1), max(ebottom, lbottom)

    return [
        max(0, ex0),
        max(0, etop),
        min(page.width, ex1),
        min(page.height, ebottom),
    ]


def collect_images(pdf, ch: dict, nxt: dict | None, boxes: list[dict],
                   total_pages: int) -> list[dict]:
    """收集章节范围内的【插图】（排除表格里的图形）

    为什么要把图片位置记下来：

        PDF 里"图"和"图上的标注文字"是分开的对象 —— 图是一个图形对象，
        标注文字是独立的文本对象，PDF 不知道它们有关系。

        但我们的用法是：
          · 检索靠文字（图注文字照常提取，负责"能被搜到"）
          · 回答时把【原图】渲染出来给模型看（模型能看懂图，不需要预先做文字描述）

        所以 chunk 里要记下"这张图在哪（页码 + bbox）"，到时候按位置渲染。

    注意排除【表格内】的图形 —— 那些是按键图标之类，已经由表格逻辑处理过了。
    """
    start = (ch["found_page"], ch["top"])
    end = (nxt["found_page"], nxt["top"]) if nxt else None
    last_page = nxt["found_page"] if nxt else total_pages

    images = []
    for page_no in range(ch["found_page"], last_page + 1):
        page = pdf.pages[page_no - 1]
        for g in graphics_in(page):         # g = (x0, top, x1, bottom)
            pos = (page_no, g[1])
            if not pos_lt(start, pos):
                continue
            if end and not pos_lt(pos, end):
                break
            # 表格内的图形不算插图
            if line_in_any_table(page_no, g[1], boxes):
                continue
            # 把图形 bbox 扩成"图 + 周围标注"的完整范围，
            # 否则渲染出来的图会缺掉四周的文字标注（实测踩过）
            expanded = expand_to_include_labels(page, g)
            images.append({
                "page": page_no,
                "bbox": [round(v, 1) for v in expanded],
                "w": round(expanded[2] - expanded[0], 1),
                "h": round(expanded[3] - expanded[1], 1),
            })
    return images


def tables_in_range(chains: list[list[dict]], start: tuple, end: tuple | None) -> list:
    """找出起点落在 [start, end) 区间内的表格链"""
    result = []
    for chain in chains:
        first = chain[0]
        pos = (first["page"], first["sig"]["top"])
        if not pos_lt(start, pos):
            continue
        if end and not pos_lt(pos, end):
            continue
        result.append(chain)
    return result


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python build_chunks.py <PDF路径>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not Path(pdf_path).exists():
        print(f"文件不存在: {pdf_path}")
        sys.exit(1)

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        print(f"文件: {pdf_path}  |  共 {total} 页\n")

        # ---- 1. 章节定位 ----
        toc_pages = find_toc_pages(pdf, 15)
        chapters = [e for _, entries in toc_pages for e in entries]
        last_toc = max(p for p, _ in toc_pages)
        located = locate_chapters(pdf, chapters, start_page=last_toc + 1)
        stacks = build_stack(located)
        print(f"章节数: {len(located)}")

        # ---- 2. 表格（含跨页合并）----
        items = collect_tables(pdf, 1, total)
        chains = build_chains(items)
        boxes = table_boxes(chains)
        merged_cnt = sum(1 for c in chains if len(c) > 1)
        print(f"表格链: {len(chains)} 条（其中跨页 {merged_cnt} 条）")

        img_cnt = sum(1 for it in items for row in it["rows"] for c in row
                      if c == "[圖示]")
        print(f"图示标记: {img_cnt} 处\n")

        # ---- 3. 先算完所有章节（后面汇总和详情都用这份数据）----
        chunks = []
        for i, ch in enumerate(located):
            nxt = located[i + 1] if i + 1 < len(located) else None
            start = (ch["found_page"], ch["top"])
            end = (nxt["found_page"], nxt["top"]) if nxt else None
            chunks.append({
                "ch": ch,
                "nxt": nxt,
                "path": chapter_path(stacks[i]),
                "bodies": collect_bodies(pdf, ch, nxt, boxes, total),
                "tables": tables_in_range(chains, start, end),
                "images": collect_images(pdf, ch, nxt, boxes, total),
            })

        # ---- 4. 汇总表（99 个章节一眼看全）----
        print("=" * 76)
        print("汇总（每章一行）")
        print("=" * 76)
        print(f"  {'编号':<9}{'标题':<30}{'正文':>6}{'表格':>6}{'插图':>6}{'字符数':>8}")
        print("  " + "-" * 76)
        for c in chunks:
            ch = c["ch"]
            chars = sum(len(t) for t in c["bodies"])
            print(f"  {ch['number']:<9}{ch['title'][:28]:<30}"
                  f"{len(c['bodies']):>6}{len(c['tables']):>6}"
                  f"{len(c['images']):>6}{chars:>8}")

        # 挑出内容最多的几节 —— 用来判断"要不要二次切分"
        # （一个 chunk 太大的话，检索命中后给模型的上下文会过长）
        by_chars = sorted(chunks, key=lambda c: -sum(len(t) for t in c["bodies"]))[:5]
        print("\n  内容最多的 5 节（看要不要再按段落切一刀）：")
        for c in by_chars:
            ch = c["ch"]
            print(f"    {ch['number']:<9}{ch['title'][:24]:<26}"
                  f"{sum(len(t) for t in c['bodies']):>8} 字符"
                  f"  （{len(c['tables'])} 表格）")

        # ---- 5. 详情（不加参数就不打印）----
        #
        # 为什么不默认全打：99 个章节的详情有 600 多行，会撑爆终端缓冲区 ——
        # 连前面打印的汇总表都会被顶掉、滚不回去。
        only = sys.argv[2] if len(sys.argv) > 2 else None

        if only and only.lower() == "all":
            only = None                       # all = 打印全部详情
        elif not only:
            script = Path(sys.argv[0]).name
            print("\n（以上是汇总。要看详情，加个参数：")
            print(f"     python {script} <PDF路径> 1.3        # 看 1.3 开头的章节")
            print(f"     python {script} <PDF路径> all        # 看全部，建议重定向到文件：")
            print(f"     python {script} <PDF路径> all > out.txt ）")
            return
        else:
            print(f"\n详情（只显示编号以「{only}」开头的章节）")

        print("=" * 76)

        for c in chunks:
            ch, nxt = c["ch"], c["nxt"]
            if only and not ch["number"].startswith(only):
                continue
            bodies, ch_tables, ch_images = c["bodies"], c["tables"], c["images"]
            path = c["path"]
            print(f"\n【{ch['number']} {ch['title']}】")
            print(f"  路径: {path}")
            pos_txt = f"PDF {ch['found_page']} 页 top={ch['top']:.0f}"
            if nxt:
                pos_txt += f"  →  {nxt['number']} 之前"
            print(f"  范围: {pos_txt}")
            print(f"  内容: 正文 {len(bodies)} 行 | 表格 {len(ch_tables)} 个 | "
                  f"插图 {len(ch_images)} 张")

            if bodies:
                preview = " ".join(bodies[:2])[:100]
                print(f"  正文预览: {preview}...")

            for img in ch_images:
                print(f"  插图: PDF {img['page']} 页  "
                      f"{img['w']:.0f}x{img['h']:.0f} 点")

            for chain in ch_tables:
                header, body = merge_chain(chain)
                show_header = unique_headers(header)
                pages = "→".join(str(s["page"]) for s in chain)
                print(f"  表格: {len(body)} 行 × {len(header)} 列  (PDF {pages})")
                if body:
                    print(f"        首行: {row_to_text(show_header, body[0])[:90]}")

        print("\n" + "=" * 76)
        print("核对要点：")
        print("  · 每章的【正文行数】合不合理（有没有把表格文字混进来）")
        print("  · 表格有没有归到正确的章节下")
        print("  · 正文里有没有混入页眉页脚、目录文字")
        print("\n确认结构对了，下一步就可以输出成正式格式（JSON / Markdown / 直接喂给检索）")


if __name__ == "__main__":
    main()
