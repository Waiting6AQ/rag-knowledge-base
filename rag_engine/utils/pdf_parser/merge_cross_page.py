"""
跨页表格检测与合并（链式版）

============================ 问题现场（RTS-700.pdf 真实数据） ============================

    第 14 页  表格1: 7 行 x 3 列,  x1=521.7,  表头 ['按 鍵', '名 稱', '功 能']
    第 15 页  表格1: 1 行 x 3 列,  x1=521.7,  "表头" ['', '下移鍵', '① 在主介面下...']

    这两块【是同一个表】，被分页切开了。续页不会重复表头，
    所以 pdfplumber 只能把第一行数据硬当成"表头"。

============================ 为什么会"表头错乱"（旧版逐对比较的缺陷） ============================

    旧版是对【相邻两页】逐对独立判断，每轮都假定"上一页表格的第一行是表头"。
    表格只跨两页时没问题，跨三页就崩：

        117 页  表格A = [表头, 数据1, 数据2, ...]   ← 有真表头
        118 页  表格B = [数据5, 数据6, ...]          ← A 的续行，本来就没表头
        119 页  表格C = [数据17, 数据18, ...]        ← B 的续行

        第 117 轮：prev=A, cur=B  →  header 取 A[0]  ✅ 正确
        第 118 轮：prev=B, cur=C  →  header 取 B[0]  ❌ B[0] 是数据行！

    根因：脚本每一轮都是独立的，不知道"B 自己已经是 A 的续行块了"。
    好比看三个人排队，只看相邻两人的关系——看到"3 号在 2 号后面"就以为 2 号是队首。

    【修法】改成"链式累积"：是续行就接到当前链上，不是就结束这条链、另起一条。
            这样跨 N 页的表会被认成一条链，只用第一段的表头。

============================ 判断"这是同一个表"的判据（按可靠性排序） ============================

    1. 【列边界 x0 / x1 一致】（容差内）   ← 最硬：同一个表被切开，左右边界物理上不变
       实测：同表续页 x1 差 0.0 点，而同一页上另一个表是 485.7 vs 521.7
    2. 列数相同
    3. 位置特征：上一页的表延伸到页面下部，当前页的表从页面顶部开始
       —— 用【比例】不用绝对点数：页面底部有页脚占位，表格不会画到贴底
          （实测：bottom=653、页高 842，离页底 189 点，用固定阈值会漏判）
    ※ 不能用"表头文字相同"判断 —— 真实文档续页常常不重复表头

============================ 另外处理的两个真实情况 ============================

    · 续页【确实重复表头】时 → looks_like_header() 识别出来丢掉
    · 原文档【左右并排两个小表】被识别成一个 4 列表格 →
      列名会出现重复（['圖示','說明','圖示','說明']）→ unique_headers() 加序号区分

用法：
    python merge_cross_page.py <PDF路径> [起始页] [结束页]

依赖：
    pip install pdfplumber
"""
import re
import sys
from pathlib import Path

import pdfplumber

TOL = 6.0             # 坐标容差（点）
TOP_RATIO = 0.20      # 表格 top 小于页面高度的 20% → 视为"从页面顶部开始"
BOTTOM_RATIO = 0.60   # 表格 bottom 超过页面高度的 60% → 视为"延伸到页面下部"
MIN_GRAPHIC = 8.0     # 宽高都超过这个值才当作"图标"（否则是表格的边框线）
IMAGE_PLACEHOLDER = "[圖示]"   # 格子有图但没文字时填的占位符
OVERLAP_MIN = 0.5     # 图形对象至少有一半落在格子里，才算"这个格子有图"


# ==================== 文本与数据清理 ====================

# 中文之间夹杂的空格：PDF 排版引擎为了对齐，会把一个词拆到不同位置，
# 按坐标还原时就成了"自 動進入"这种。检索时搜"自动"就匹配不上了，所以要清掉。
# 用后顾/前瞻断言：只有"空格前面是中文、后面也是中文"才删 —— 不碰 Shift 键这种中英混排
# 一-鿿 = Unicode 的 CJK 汉字基本区（全部常用汉字）。
_CN_SPACE = re.compile(r"(?<=[一-鿿])\s+(?=[一-鿿])")


def clean_text(s: str) -> str:
    """清理单元格文本：换行压平 + 去掉被排版拆出来的中文空格

    两步：
      1. " ".join(split()) —— 按任意空白切开再拼回，
         把换行压平成空格、同时合并连续空白（原表常用换行分 ①②③ 几点）
      2. 正则去掉"中文 + 空格 + 中文"里的空格
    """
    text = " ".join(str(s).split())
    return _CN_SPACE.sub("", text)


def rows_of(table: list) -> list[list[str]]:
    """表格 → 规整的二维字符串数组

    三件事：None 单元格 → 空串、去首尾空白、压平单元格内换行。

    注意：这里【不过滤空行】—— 因为后面要给"有图示的空单元格"填占位符，
    必须让行下标和 find_tables() 给的行列结构一一对应，否则标记会错位。
    """
    return [[clean_text(c) if c else "" for c in row] for row in (table or [])]


# ==================== 纵向合并单元格填充 ====================

def fill_vertical_merges(rows: list[list[str]], finder) -> list[list[str]]:
    """把纵向合并的单元格补回去

    ==================== 问题 ====================

    说明书里的规格表常有一个"类别"跨好几行：

        ['基本参数', '产品型号', 'FB-X100']
        ['',         '额定容量', '4L']        ← 丢了"基本参数"
        ['',         '额定功率', '800W']      ← 丢了"基本参数"

    转成"每行带列名"的文本后，后两行就没有类别信息了。

    ==================== 怎么区分"合并"和"真的空" ====================

    这是关键 —— 无脑"向下填充"会把真正的空格子也填上假数据。

    实测发现 pdfplumber 用【不同的东西】表示这两种情况：

        finder.rows[r].cells[c] 是 None    →  这一格属于某个合并区域（要填）
        finder.rows[r].cells[c] 是有 bbox 的对象  →  独立单元格（空就让它空着）

    所以判断很精确，不用猜。

    ==================== 填什么 ====================

    向上找最近的有值单元格，把它的值搬下来。
    （合并单元格的值只写在【第一行】，所以往上找一定能找到）
    """
    if not rows or not rows[0]:
        return rows

    n_rows, n_cols = len(rows), len(rows[0])
    result = [list(r) for r in rows]

    for c in range(n_cols):
        for r in range(1, n_rows):
            if result[r][c]:
                continue                       # 这格有值，不用管

            # 这一格是"合并区域的一部分"吗？
            try:
                cell = finder.rows[r].cells[c]
            except (IndexError, AttributeError):
                continue
            if cell is not None:
                continue                       # 独立单元格，空就空着

            # 是合并格 → 向上找最近的值填下来
            for k in range(r - 1, -1, -1):
                if result[k][c]:
                    result[r][c] = result[k][c]
                    break

    return result


# ==================== 图示检测 ====================

def graphics_in(page) -> list[tuple]:
    """收集页面上所有"可能是图标"的图形对象的 bbox

    两个要点（都是实测踩出来的）：

      1. 图标可能是【嵌入图片】也可能是【矢量图形】：
           page.images → 位图（PNG/JPEG）
           page.curves → 矢量曲线（从设计软件导出 PDF 时，图标常是矢量画的）
         同一份文档里两种都会用（实测 6 个图标里 2 个是图片、4 个是矢量），
         只查一种会漏掉一半。

      2. 要过滤 + 去重：
          · 表格的边框线也是图形对象 → 用面积过滤（细长条的宽或高很小）
          · 某些 PDF 把同一个形状拆成"填充 + 描边"两次绘制，
            bbox 完全相同 → 按坐标去重
    """
    boxes = []
    for it in list(page.images) + list(page.curves):
        w = it["x1"] - it["x0"]
        h = it["bottom"] - it["top"]
        if w >= MIN_GRAPHIC and h >= MIN_GRAPHIC:
            boxes.append((it["x0"], it["top"], it["x1"], it["bottom"]))

    seen, unique = set(), []
    for b in boxes:
        key = tuple(round(v, 1) for v in b)
        if key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def overlap_ratio(cell_bbox, g_bbox) -> float:
    """图形对象有多大比例落在单元格里（0~1）

    用"占比"而不是"是否相交"：表格边框常常只是擦过单元格边缘，
    按相交判断的话每个格子都会被误标成"有图"。
    """
    cx0, ctop, cx1, cbottom = cell_bbox
    gx0, gtop, gx1, gbottom = g_bbox
    ix0, itop = max(cx0, gx0), max(ctop, gtop)
    ix1, ibottom = min(cx1, gx1), min(cbottom, gbottom)
    if ix1 <= ix0 or ibottom <= itop:
        return 0.0
    inter = (ix1 - ix0) * (ibottom - itop)
    area = (gx1 - gx0) * (gbottom - gtop)
    return inter / area if area else 0.0


def image_cells(page, finder) -> set[tuple[int, int]]:
    """找出表格里"格子内画了图示"的位置，返回 {(行, 列), ...}"""
    graphics = graphics_in(page)
    if not graphics:
        return set()

    marked = set()
    for r_idx, row in enumerate(finder.rows):
        for c_idx, cell in enumerate(row.cells):
            if cell is None:
                continue
            cell_bbox = getattr(cell, "bbox", cell)
            for g in graphics:
                if overlap_ratio(cell_bbox, g) >= OVERLAP_MIN:
                    marked.add((r_idx, c_idx))
                    break
    return marked


# ==================== 表格特征与收集 ====================

def signature(finder) -> dict | None:
    """取表格的"物理指纹"：列边界 + 位置（判断跨页的唯一物理依据）"""
    bbox = getattr(finder, "bbox", None)
    if not bbox:
        return None
    x0, top, x1, bottom = bbox
    return {"x0": x0, "top": top, "x1": x1, "bottom": bottom}


def collect_tables(pdf, start: int, end: int) -> list[dict]:
    """把指定范围内的所有表格按阅读顺序收集成一个列表

    每一项记录：页码、页内序号、内容、坐标、是否本页首/末个表格。
    "是否本页首/末"很重要 —— 只有"上页的最后一个"才可能接到"下页的第一个"。

    顺带做一件事：把"画了图但文字层提取不到"的格子填上 [圖示] 占位符。
    这样后面的合并、转文本逻辑完全不用改 —— 占位符就跟普通文本一样流转，
    但信息不再丢失（读者知道这一格原本有内容）。
    """
    items = []
    for page_no in range(start, end + 1):
        page = pdf.pages[page_no - 1]
        finders = page.find_tables()      # 分析一次，复用（不要在循环里反复调）
        tables = page.extract_tables()

        for idx, (table, finder) in enumerate(zip(tables, finders)):
            rows = rows_of(table)
            sig = signature(finder)
            if not rows or not sig:
                continue

            # 纵向合并填充：把跨行的分类列补回去。
            #
            # 【顺序很重要】必须在"图示占位"之前做 ——
            # 图示占位只会往【空格子】里填 [圖示]，如果先填了占位符，
            # 合并单元格那个"空"就没了，纵向填充会整列漏掉。
            rows = fill_vertical_merges(rows, finder)

            # 图示占位：只填"格子为空、但那里确实画了图形"的位置
            for r, c in image_cells(page, finder):
                if r < len(rows) and c < len(rows[r]) and not rows[r][c]:
                    rows[r][c] = IMAGE_PLACEHOLDER

            items.append({
                "page": page_no,
                "idx": idx,
                "rows": rows,
                "sig": sig,
                "page_height": page.height,
                "is_first_on_page": idx == 0,
                "is_last_on_page": idx == len(tables) - 1,
            })
    return items


# ==================== 判断与合并 ====================

def is_continuation(prev: dict, cur: dict) -> bool:
    """判断 cur 是不是 prev 的跨页续行"""
    # 前提：必须是"上页最后一个" → "下页第一个"，且页码相邻
    if cur["page"] != prev["page"] + 1:
        return False
    if not prev["is_last_on_page"] or not cur["is_first_on_page"]:
        return False

    # 判据 1：列数相同
    if len(prev["rows"][0]) != len(cur["rows"][0]):
        return False

    # 判据 2：列边界一致 —— 最可靠
    if abs(prev["sig"]["x0"] - cur["sig"]["x0"]) > TOL:
        return False
    if abs(prev["sig"]["x1"] - cur["sig"]["x1"]) > TOL:
        return False

    # 判据 3：位置特征（上页写到底、下页从头起）
    if prev["sig"]["bottom"] < prev["page_height"] * BOTTOM_RATIO:
        return False
    if cur["sig"]["top"] > cur["page_height"] * TOP_RATIO:
        return False

    return True


def build_chains(items: list[dict]) -> list[list[dict]]:
    """把所有表格按跨页关系串成"链"

    是续行 → 接到当前链上；不是 → 结束当前链，另起一条。
    这样跨 3 页、5 页的表格都是同一条链，后续只用第一段的表头。
    """
    if not items:
        return []
    chains = []
    current = [items[0]]
    for prev, cur in zip(items, items[1:]):
        if is_continuation(prev, cur):
            current.append(cur)
        else:
            chains.append(current)
            current = [cur]
    chains.append(current)
    return chains


def looks_like_header(row: list[str], header: list[str]) -> bool:
    """判断某一行是不是表头（有些文档的续页会重复表头，要丢掉）"""
    if len(row) != len(header):
        return False
    same = sum(1 for a, b in zip(row, header) if a and b and a == b)
    return same >= max(2, len(header) - 1)


def fill_blank_rows(rows: list[list[str]]) -> list[list[str]]:
    """链合并之后的"空值向下填充" —— 专门处理【合并单元格跨页】

    ==================== 为什么还要单独填一次 ====================

    段内的填充（fill_vertical_merges）靠 pdfplumber 的 None 标记，很精确。
    但合并单元格【跨页】时，下半段在下一页 ——
    那一段里压根没有"基本参数"这个字符串，按段往上找是找不到的：

        第 14 页末：| 基本参数 | 产品型号 | FB-X100 |   ← 值在这页
        第 15 页首：|          | 额定功率 | 800W    |   ← 空，填不上 ✗

    两段被 merge_chain 拼成一张完整的表之后，再补这一次填充就能接上。

    ==================== 为什么是"向上找最近的值" ====================

    合并单元格的值，pdfplumber 只写在【最上面那一行】——
    因为合并区域是一个矩形，文字画在里面，按文字上边缘归属就落到了第一行。
    所以要填下面的空行，只能从上面拿：一个值管住它下面那几行。

    ==================== 为什么所有列都填（不是只填第一列） ====================

    纵向合并【不是只发生在第一列】—— "项目"列也可能合并
    （比如"外形尺寸"下面挂"长/宽/高"）。限制列反而会漏填。

    这时手里已经没有 None 标记了，只能靠"空值填充"，有误填真空格的风险。但：
      · 段内的合并已经被精确填过了，剩下的空格要么是真空、要么是跨页合并
      · 误填的代价不大 —— 填进去的是同一列上面的值，语义上本来就相关
      · 不填的代价更大（分类信息直接丢了）
    """
    if not rows or not rows[0]:
        return rows

    result = [list(r) for r in rows]
    n_cols = len(result[0])

    for c in range(n_cols):
        last = ""
        for r in range(len(result)):
            if result[r][c]:
                last = result[r][c]        # 更新"当前列最近的值"
            elif last:
                result[r][c] = last        # 空 → 沿用上面的值

    return result


def merge_chain(chain: list[dict]) -> tuple[list[str], list[list[str]]]:
    """把一条链上的所有段合并成 (表头, 数据行列表)

    表头只取【第一段】的第一行；后面每段的第一行可能是重复表头，识别出来丢掉。
    """
    first_rows = chain[0]["rows"]
    header = first_rows[0] if first_rows else []
    body = first_rows[1:]

    for seg in chain[1:]:
        rows = seg["rows"]
        if rows and looks_like_header(rows[0], header):
            rows = rows[1:]      # 丢掉重复表头
        body.extend(rows)

    # 所有段拼完之后再补一次填充 —— 处理【合并单元格跨页】：
    # 下半段在下一页，按段填充找不到上一页那个值，得等两段拼好了才接得上。
    #
    # 【只对跨页的链做】—— 单段的表格里，段内填充（靠 pdfplumber 的 None 标记）
    # 已经精确处理过了；再填一遍反而会把"真正的空格子"也填上假数据。
    if len(chain) > 1:
        body = fill_blank_rows(body)

    return header, body


def unique_headers(header: list[str]) -> list[str]:
    """列名重复时加序号区分

    原文档里【左右并排两个小表格】会被识别成一个 4 列表格，
    列名就成了 ['圖示', '說明', '圖示', '說明'] —— 转文本时两个"說明"
    分不清谁是谁。加序号后变成 ['圖示1','說明1','圖示2','說明2']。
    """
    counts: dict[str, int] = {}
    for h in header:
        counts[h] = counts.get(h, 0) + 1

    seen: dict[str, int] = {}
    result = []
    for h in header:
        if counts[h] > 1 and h:
            seen[h] = seen.get(h, 0) + 1
            result.append(f"{h}{seen[h]}")
        else:
            result.append(h)
    return result


def row_to_text(header: list[str], row: list[str]) -> str:
    """一行数据 → 「自带上下文」的文本

    每个值都带上前面的列名，这样即使这一行被单独检索到，
    模型也知道它在说什么 —— 这是解决"归位不准"的核心思路。
    列名为空的格子只输出值本身。
    """
    parts = []
    for h, v in zip(header, row):
        if not v:
            continue
        parts.append(f"{h}：{v}" if h else v)
    return "；".join(parts)


# ==================== 主流程 ====================

def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python merge_cross_page.py <PDF路径> [起始页] [结束页]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not Path(pdf_path).exists():
        print(f"文件不存在: {pdf_path}")
        sys.exit(1)

    start = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    end_arg = int(sys.argv[3]) if len(sys.argv) > 3 else None

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        end = min(end_arg or total, total)
        print(f"文件: {pdf_path}  |  共 {total} 页，扫描范围 {start}-{end}\n")

        items = collect_tables(pdf, start, end)
        chains = build_chains(items)
        multi = [c for c in chains if len(c) > 1]

        # 统计图示占位数量（有图但文字层提取不到的格子）
        img_total = sum(
            1 for it in items for row in it["rows"] for c in row
            if c == IMAGE_PLACEHOLDER
        )

        print(f"共扫描 {len(items)} 个表格，串成 {len(chains)} 条链，"
              f"其中【跨页的 {len(multi)} 条】")
        print(f"检测到 {img_total} 处图示（有图但提取不到文字，已用 {IMAGE_PLACEHOLDER} 占位）\n")

        # 没有跨页表格时：把每个表格的内容都打印出来
        # （方便单独检查某一页 —— 比如只想验证图示标记对不对）
        if not multi:
            print("（本范围内没有跨页表格 —— 打印各表格内容）\n")
            for it in items:
                rows = it["rows"]
                if not rows:
                    continue
                show_header = unique_headers(rows[0])
                print(f"--- 第 {it['page']} 页 表格{it['idx'] + 1}："
                      f"{len(rows) - 1} 行数据 ---")
                for r in rows[1:]:
                    print(f"    {row_to_text(show_header, r)}")
                print()

        for i, chain in enumerate(multi, 1):
            header, body = merge_chain(chain)
            show_header = unique_headers(header)
            pages = f"{chain[0]['page']}"
            if len(chain) > 1:
                pages += f" → {chain[-1]['page']}"
            x1_last = chain[-1]["sig"]["x1"]

            print("=" * 64)
            print(f"【跨页表格 {i}】第 {pages} 页 | {len(chain)} 段 | "
                  f"列数 {len(header)} | x1 差 {abs(chain[0]['sig']['x1'] - x1_last):.1f} 点")
            print(f"  合并后：{len(body)} 行数据")
            print(f"  表头  ：{show_header}")

            # 重复列名的情况单独说明（并排表格）
            if len(set(header)) != len(header):
                print(f"  ⚠ 列名有重复，已加序号区分：原表头 {header}")

            print(f"\n  最后 2 行转成【自带上下文】的文本：")
            for r in body[-2:]:
                print(f"    {row_to_text(show_header, r)}")

    print("\n" + "=" * 64)
    print("下一步：把这个「每行自带列名」的文本按章节切块，"
          "整表作为一个切块单元，不再从中间切开。")


if __name__ == "__main__":
    main()
