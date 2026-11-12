"""
定位章节在页面上的精确位置，并划分内容范围

============================ 核心思路：文字用来"找"，坐标用来"分" ============================

【找】标题 —— 用文字匹配就够了（正文里就有标题文字）。
【分】内容 —— 必须用坐标，因为纯文字切分有三个坑：

    坑1【目录页也含标题文字】
        目录里有全部 99 个标题，按文字切会把目录页也当成章节内容。

    坑2【表格不是文本流】
        表格有行列结构、跨页合并、图示标记 —— 这些是前面辛苦提取的成果。
        用 extract_text() 拿到的是"一坨文字"，行列关系全丢。
        所以表格必须【结构化提取】，再单独挂到所属章节下。

    坑3【一页里有多个章节】
        实测第 14 页同时有 "1.3 鍵盤及觸摸屏" 和 "1.3.1 鍵盤" 两个标题。
        只知道"在 14 页"不够 —— 得知道标题在页面的【哪个位置】，
        才能判断下半页那个表格到底属于 1.3 还是 1.3.1。

所以定位就是一步：在正文里搜标题文字，记下它离页顶多远（top 坐标）。

============================ 怎么找标题 ============================

对每个章节：
    1. 先去它目录给的页码那一页找
    2. 在该页的文本行里搜标题文字（【去掉所有空格】再比 ——
       PDF 提取出来的中文常被排版拆开带空格，不去掉匹配不上）
    3. 找到就记下 top 坐标；那一页没找到，就前后各扩一页再试

============================ 输出什么 ============================

按阅读顺序排列的章节，每个带精确位置，并自动算出内容范围：

    章节A 的起点 → 章节B 的起点，中间就是 A 的内容范围

先跑这个、人工核对范围划得对不对，再动手提取内容。

用法：
    python locate_chapters.py <PDF路径> [扫描页数]

依赖：
    pip install pdfplumber
"""
import re
import sys
import unicodedata
from pathlib import Path

import pdfplumber

# 复用 parse_toc.py 里的目录解析和页码换算逻辑
from .parse_toc import find_toc_pages, find_pdf_page_of

def line_matches_title(line_text: str, number: str, title: str) -> bool:
    """判断这一行是不是某个章节的标题行 —— 用【编号 + 完整标题】匹配

    为什么带上编号，而不是只匹配标题文字：
        短标题会误匹配到长标题所在的行。实测踩过：
            "1.3.1 鍵盤" 的标题是 "鍵盤"，而页面上有一行是 "1.3 鍵盤及觸摸屏"
            —— 它的子串里正好包含 "鍵盤"，只比标题的话会匹配到那一行去，
               结果两个章节被定位到同一个位置（top 都是 97.2）。
        加上编号前缀（"1.3.1鍵盤"）就区分开了。

    编号和标题之间可能有分隔符 —— 一级标题排版成 "1. 儀器各部位名稱及其功能"，
    编号后面带个点；二级标题则是 "2.3 雙速止微動說明"，编号后直接是空格。
    所以用正则允许一个【可选的点】。

    ==================== 为什么不能要求完整匹配 ====================

    【目录和正文的标题文字本身就可能不一致】—— 截图确认过的例子：

        目录写：2.3 雙速止微動說明
        正文写：2.3 雙速止微動"機構"說明        ← 多了两个字

        目录写：2.5 用鐳射對"電"器置中儀器
        正文写：2.5 用鐳射對"點"器置中儀器      ← 一个字不同

    这是文档自身的问题（目录和正文大概不是同一版做的）。
    要求完整匹配的话，这些标题永远定位不到。

    ==================== 匹配策略：编号 + 标题前几个字 ====================

      · 必须以【编号】开头  —— 编号在文档里是唯一的（"2.3" 只对应这一节），
        不会串到别处；而且能排除正文里的交叉引用
        （"参见 2.3 节"这类不会以编号开头）
      · 编号后面紧跟【标题的前 3 个字】—— 足够确认是不是这个标题，
        同时容忍后面的增删改

    ==================== 另外：Unicode 归一化 ====================

    PDF 里有些字用【兼容汉字区】（U+F900~U+FAFF）的码点，显示和标准汉字
    一样但在程序里是不同的字符（实测这份文档里就有：輪 U+F9D7、螺 U+F911、
    連 U+F99A）。所以匹配前先做 NFKC 归一化，把兼容字统一成标准形式。
    """
    t = unicodedata.normalize("NFKC", line_text).replace(" ", "").replace("　", "")
    num = unicodedata.normalize("NFKC", number)
    ttl = unicodedata.normalize("NFKC", title).replace(" ", "")

    # 编号【不一定在行首】，而且分隔符也可能不统一。两种真实情况叠加：
    #   正文写 "-- 3. 儀器設置"  → 行首有装饰符号（具体是什么字符不好穷举）
    #   正文写 "7、4線路測量"    → 编号里的点被写成了顿号
    #
    # 所以：先取行首一小段（编号只可能出现在这里），把分隔符归一化成点，
    # 再在这一段里找编号。替换是 1:1 的，不改变长度，所以下标可以直接用。
    zone = re.sub(r"[、．。]", ".", t[:8])
    idx = zone.find(num)
    if idx == -1 or idx > 4:        # 编号必须在行首 4 个字符以内
        return False

    rest = t[idx + len(num):].lstrip(".、　")
    # 只比标题的【前 2 个字】—— 因为目录和正文常常从第 3 个字开始就不一样了。
    # 实测三个这样的例子：
    #     目录 7.4  線路【測量】  vs  正文 線路【設置】
    #     目录 8.5  光學【對】點器… vs  正文 光學【下】對點器…
    #     目录 2.10 儀器【於】電腦… vs  正文 儀器【與】電腦…
    # 之所以敢降到 2 个字，是因为外面还有两层约束兜着：
    #   ① 编号必须匹配（"7.4" 在文档里唯一）② 编号必须在行首 4 个字符内
    # 两者叠加已经把范围锁死了，前 2 个字只做二次确认。
    return rest.startswith(ttl[:2]) if ttl else True


def locate_chapters(pdf, chapters: list[dict], start_page: int) -> list[dict]:
    """按【阅读顺序】逐个定位章节 —— 不依赖目录页码

    ==================== 为什么不用页码去找 ====================

    目录给的是【印刷页码】，它和 PDF 页序之间的偏移【不是恒定的】。
    实测这份文档：

        前段：印刷 1  → PDF 11   偏移 +10
        中段：印刷 16 → PDF 27   偏移 +11   ← 变了！

    说明正文中间插了页（彩色插图页 / 折页 / 没编号的页）。
    一旦偏移变了，后面所有章节按页码找全都会失败。

    ==================== 改成顺序搜索 ====================

    章节在文档里出现的【先后顺序】是确定的（目录给了顺序），
    所以：从上一章找到的位置往后搜，找到就用。

        第 1 章 → 从 start_page 往后搜 → 位置 P1
        第 2 章 → 从 P1 往后搜         → 位置 P2
        ...

    完全不依赖偏移量，偏移怎么变都不影响。

    start_page 必须是【目录页之后】的页码 —— 否则第一章会匹配到
    目录页里那行标题（目录里列了全部 99 个标题）。

    返回的每项多两个字段：
        found_page : 实际定位到的 PDF 页（None = 没找到）
        top        : 标题行的 top 坐标（None = 没找到）
    """
    located = []
    cursor = start_page          # 搜索游标：下一章从这一页开始搜

    for ch in chapters:
        hit = None
        for page_no in range(cursor, len(pdf.pages) + 1):
            page = pdf.pages[page_no - 1]
            for line in page.extract_text_lines():
                text = line.get("text") or ""
                if not text:
                    continue
                if line_matches_title(text, ch["number"], ch["title"]):
                    hit = {"found_page": page_no, "top": line["top"]}
                    break
            if hit:
                cursor = page_no      # 下一章从这一页（或之后）继续
                break
        located.append({**ch, **(hit or {"found_page": None, "top": None})})

    return located


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python locate_chapters.py <PDF路径> [扫描页数]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not Path(pdf_path).exists():
        print(f"文件不存在: {pdf_path}")
        sys.exit(1)

    max_scan = int(sys.argv[2]) if len(sys.argv) > 2 else 15

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        print(f"文件: {pdf_path}  |  共 {total} 页\n")

        # ---- 1. 解析目录 ----
        toc_pages = find_toc_pages(pdf, max_scan)
        if not toc_pages:
            print("没找到目录页，先跑 parse_toc.py 检查")
            return
        chapters = [e for _, entries in toc_pages for e in entries]

        # ---- 2. 页码换算 ----
        anchor = next((c for c in chapters if c["level"] == 1), None)
        offset = 0
        if anchor:
            last_toc = max(p for p, _ in toc_pages)
            actual = find_pdf_page_of(pdf, anchor["title"], last_toc + 1)
            if actual:
                offset = actual - anchor["page"]
        for c in chapters:
            c["pdf_page"] = c["page"] + offset
        print(f"偏移量 {offset:+d} | 章节数 {len(chapters)}\n")

        # ---- 3. 定位（顺序搜索，从目录页之后开始，避开目录里的标题行）----
        last_toc_page = max(p for p, _ in toc_pages)
        located = locate_chapters(pdf, chapters, start_page=last_toc_page + 1)
        missing = [c for c in located if c["top"] is None]

        # ---- 4. 打印结果 + 内容范围 ----
        print("=" * 76)
        print("章节定位（按阅读顺序）")
        print("=" * 76)

        for i, ch in enumerate(located):
            nxt = located[i + 1] if i + 1 < len(located) else None
            if ch["top"] is not None:
                pos = f"PDF {ch['found_page']:>3} 页  top={ch['top']:>6.1f}"
            else:
                pos = "【未定位】"

            print(f"\n  L{ch['level']} {ch['number']:<8} {ch['title'][:32]:<34}  {pos}")

            if nxt:
                print(f"      范围 → 到 [{nxt['number']} {nxt['title'][:18]}] 之前")
            else:
                print(f"      范围 → 到文档末尾")

        print(f"\n{'=' * 76}")
        if missing:
            print(f"⚠ {len(missing)} 个章节没定位到（标题文字和目录不一致，或跨页）：")
            for c in missing[:10]:
                print(f"    L{c['level']} {c['number']} {c['title']}")
        else:
            print("✓ 所有章节都定位到了")

        print("\n核对要点：")
        print("  · 每个章节的起点是不是真的在那个位置（对着 PDF 抽查几页）")
        print("  · 范围有没有交叉或漏掉（每章应该紧接下一章）")
        print("  · 未定位的章节是怎么回事")
        print("\n确认范围划得对，下一步就按范围填内容：")
        print("  正文段落（文字提取）+ 表格（结构化，含合并和图示）+ 图示标记")


if __name__ == "__main__":
    main()
