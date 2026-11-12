"""
解析【目录页】，提取章节结构

============================ 为什么用目录页 ============================

这份 PDF 没有内置书签，但开头几页有目录 —— 那上面白纸黑字写着
"章节名 ...... 页码"，等于把章节结构直接给了我们：

    · 层级 —— 靠编号的段数判断（"1"=一级，"1.3"=二级，"1.3.1"=三级）
    · 标题文字 —— 准确的，不用猜
    · 页码 —— 现成的

比"用字号猜标题"可靠得多。

============================ 已经探明的事实（RTS-700.pdf） ============================

【目录页位置】PDF 第 5~8 页（可能更多）

【页码有两套】这点很容易踩坑：
    前半部分（注意事项/免责/目录）用一套页脚编号：PDF第2页=-1-、第3页=-2- ...
    正文另起一套：键盘那节印着 -4-，但它在 PDF 第 14 页
    → 所以【不能靠页脚数字判断】，得用别的方式锚定（见下）

【目录行格式】
    1. 儀器各部位名稱及其功能................................... 1
    1.1 部件名稱............................................ 1
    1.2.1 系統主介面.....................................3
    ↑ 编号  ↑ 标题          ↑ 点线（英文句点）  ↑ 页码（前面空格数不定）

============================ 页码怎么换算 ============================

不假设偏移量，而是【找一个已知章节，搜它在正文里实际出现在第几页】：

    目录说 "1. 儀器各部位名稱及其功能 在第 1 页"
    → 去正文里搜这段标题，发现实际在 PDF 第 11 页
    → 偏移 = 11 - 1 = 10
    → 其余章节的 PDF 页序 = 印刷页码 + 10

用 search 而不是 match 匹配目录行，还能自动跳过排版残留
（实测有一行是 "64 5.10 雙距偏心......63"，前面多了个 64）。

用法：
    python parse_toc.py <PDF路径> [扫描页数，默认 15]

依赖：
    pip install pdfplumber
"""
import re
import sys
from pathlib import Path

import pdfplumber

# 目录行的【常见排版格式】—— 不同文档长得不一样，按顺序试，哪个能匹配用哪个
#
# 这是"目录解析"里唯一需要按文档适配的地方：
# 后面的逻辑（顺序搜索、编号 + 前 2 字匹配）都是通用的。
TOC_PATTERNS = [
    # ① 编号 + 标题 + 点线 + 页码
    #      "1.3.1 鍵盤 ................................. 4"
    #    · \.?   —— 一级标题的编号带个尾巴点（"1. 儀器各部位..."），
    #               不加这个可选点的话，"1" 后面那个 "." 会卡住匹配
    #    · \.{2,} —— 要求至少两个点，避免把 "1.2 标题" 里的点当成点线
    re.compile(r"(\d+(?:\.\d+)*)\.?\s+(.+?)\.{2,}\s*(\d+)\s*$"),

    # ② 编号 + 标题 + 空格 + 页码（【没有点线】）
    #      "1.1 系统组成 13"
    #      "3.6 距离测量 - 正确观测注意事项 41"
    #    这类目录的标题和页码之间只有【一个空格】——
    #    实测 Leica 手册就是这样，一开始我按"至少两个空格"写，完全匹配不上。
    #
    #    为什么这样不会把"标题里的空格"误当成分隔：
    #      · (.+?) 是非贪婪的，会尽量少匹配
    #      · 但后面要求 \s+(\d+)\s*$ —— 页码必须是【行尾的纯数字】
    #      · 所以遇到 "距离测量 - 正确观测注意事项 41" 时，
    #        非贪婪会一路回溯到最后一个"空格 + 数字 + 行尾"的位置 ✓
    re.compile(r"(\d+(?:\.\d+)*)\.?\s+(.+?)\s+(\d+)\s*$"),
]


def parse_toc_lines(text: str) -> list[dict]:
    """从一页的文本里解析出目录条目

    返回 [{number, title, page, level}, ...]
        number: 章节号（"1" / "1.3" / "1.3.1"）
        title : 标题文字
        page  : 目录里写的页码（正文的印刷页码）
        level : 层级 —— 靠编号里的点数判断，1 个点是二级，2 个点是三级
    """
    entries = []
    for line in text.split("\n"):
        # 按顺序试几种目录排版格式，用【第一个能匹配上的】——
        # 这样加新格式时不用改动后面的逻辑
        matches = []
        for pattern in TOC_PATTERNS:
            matches = list(pattern.finditer(line))
            if matches:
                break
        if not matches:
            continue

        # 一行可能匹配到多个 —— 排版残留会在行首多出个数字，
        # 比如实测有一行是 "64 5.10 雙距偏心......63"：
        #   匹配1 → number="64",    title="5.10 雙距偏心"   ← 假的（64 是残留）
        #   匹配2 → number="5.10",  title="雙距偏心"        ← 真的
        # 判据：真标题不该以数字开头 —— 以数字开头说明前面的数字是残留
        chosen = None
        for m in matches:
            if not re.match(r"^\d", m.group(2).strip()):
                chosen = m
                break
        if chosen is None:
            chosen = matches[-1]      # 兜底

        number, title, page = chosen.groups()
        title = title.strip()

        # 后处理：标题自己以【章节号】开头时，说明前面的数字是脏数据。
        # 实测文档里真有这种行（截图确认过原文如此，不是提取错误）：
        #     64    5.10  雙距偏心.........................63
        # 那个孤立的 "64" 既不是本行页码(63)、也不是上一节的(61)，是排版多出来的。
        # 不处理的话，章节树里会多出一个假的 L1 "64"，后面按章节归位就全错了。
        #
        # 为什么前面"挑标题不以数字开头的匹配"那一步没拦住它：
        #   finditer 找的是【不重叠】匹配 —— 从行首 "64" 开始的那个匹配会一路
        #   吃到行尾，整行被它吃完了，压根没有第二个匹配可挑。
        #
        # 所以这里再拆一次："64 5.10 雙距偏心" → number="5.10", title="雙距偏心"
        #   ※ 要求"数字.数字"形式（至少一个点），免得误伤 "RTS700系列..." 这类正常标题
        fix = re.match(r"^(\d+(?:\.\d+)+)\s+(.+)$", title)
        if fix:
            number, title = fix.group(1), fix.group(2).strip()

        entries.append({
            "number": number,
            "title": title.strip(),
            "page": int(page),
            "level": number.count(".") + 1,      # "1"→1, "1.3"→2, "1.3.1"→3
        })
    return entries


def find_toc_pages(pdf, max_scan: int) -> list[tuple[int, list[dict]]]:
    """找出目录页：一页里匹配到 3 条以上目录行，就认为是目录页"""
    pages = []
    for i in range(min(max_scan, len(pdf.pages))):
        text = pdf.pages[i].extract_text() or ""
        entries = parse_toc_lines(text)
        if len(entries) >= 3:
            pages.append((i + 1, entries))
    return pages


def find_pdf_page_of(pdf, text: str, start_page: int) -> int | None:
    """在正文里搜某段文字，返回它首次出现的 PDF 页序（1 起算）

    匹配时【去掉所有空格】再比 —— PDF 提取出来的中文常带多余空格
    （排版把词拆开了），不去掉的话匹配不上。
    """
    target = text.replace(" ", "")
    for i in range(start_page - 1, len(pdf.pages)):
        page_text = (pdf.pages[i].extract_text() or "").replace(" ", "").replace("\n", "")
        if target in page_text:
            return i + 1
    return None


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python parse_toc.py <PDF路径> [扫描页数]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not Path(pdf_path).exists():
        print(f"文件不存在: {pdf_path}")
        sys.exit(1)

    max_scan = int(sys.argv[2]) if len(sys.argv) > 2 else 15

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        print(f"文件: {pdf_path}  |  共 {total} 页\n")

        # ---- 第一步：找目录页 ----
        toc_pages = find_toc_pages(pdf, max_scan)
        if not toc_pages:
            print(f"前 {max_scan} 页里没找到目录页（匹配到 3 条以上目录行的页）。")
            print("可能目录页更靠后，或者格式和预期不同 —— 用 dump_toc_text.py 看看原始文本。")
            return

        page_list = "、".join(str(p) for p, _ in toc_pages)
        all_entries = [e for _, entries in toc_pages for e in entries]
        print(f"目录页：PDF 第 {page_list} 页")
        print(f"共解析出 {len(all_entries)} 个章节条目\n")

        # ---- 第二步：算页码偏移 ----
        # 拿第一个一级标题当锚点，搜它在正文里实际出现在第几页
        anchor = next((e for e in all_entries if e["level"] == 1), None)
        offset = None
        if anchor:
            last_toc_page = max(p for p, _ in toc_pages)
            actual = find_pdf_page_of(pdf, anchor["title"], last_toc_page + 1)
            if actual:
                offset = actual - anchor["page"]
                print("=" * 64)
                print("页码换算")
                print("=" * 64)
                print(f"  锚点章节: {anchor['number']} {anchor['title']}")
                print(f"  目录说它在印刷第 {anchor['page']} 页")
                print(f"  实际在 PDF 第 {actual} 页")
                print(f"  → 偏移量 = {actual} - {anchor['page']} = {offset:+d}")
            else:
                print(f"⚠ 找不到锚点章节《{anchor['title']}》在正文的位置，无法算偏移")

        # ---- 第三步：打印章节树 ----
        print(f"\n{'=' * 64}")
        print("章节树")
        print("=" * 64)
        for e in all_entries:
            indent = "  " * (e["level"] - 1)
            pdf_page = f"PDF {e['page'] + offset:>3}" if offset is not None else "       "
            print(f"  L{e['level']} {indent}{e['number']:<8} {e['title'][:30]:<32}"
                  f" 印刷{e['page']:>3} | {pdf_page}")

        print(f"\n{'=' * 64}")
        print("核对要点：")
        print("  · 层级对不对（L1/L2/L3 的缩进和编号段数是否吻合）")
        print("  · 有没有漏条目（对着目录页看）")
        print("  · 偏移量算得对不对（抽查几个：PDF 页序 = 印刷页码 + 偏移）")
        print("\n下一步：用这份章节结构，把正文和表格归到所属章节下 ——")
        print("  某章节的 PDF 起始页 → 下一个章节的起始页之间，就是它的内容范围。")


if __name__ == "__main__":
    main()
