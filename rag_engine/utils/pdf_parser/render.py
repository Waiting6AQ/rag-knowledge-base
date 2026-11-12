"""
按 chunk metadata 里记录的 bbox 渲染 PDF 原图

结构化解析时把插图的位置（页码 + bbox）记在了 chunk 的 metadata.images 里，
这里按位置把那一块渲染成 PNG，供回答时随文字一起交给多模态模型。

为什么不预先把图转成文字描述：描述会丢信息——"图中左下角带 ON/OFF 标识的按键"
这类结论靠的是原图本身。改成按需渲染，只在命中的问答上付一次成本。
"""
import pymupdf


def render_png(pdf_path: str, page_no: int, bbox: list[float], dpi: int = 150) -> bytes:
    """把 PDF 某一页的指定区域渲染成 PNG 字节

    page_no 从 1 开始；bbox = [x0, top, x1, bottom]，原点在页面左上角。
    dpi 150 够看清按键标注，继续调高会同时放大体积和 token 消耗。
    """
    with pymupdf.open(pdf_path) as doc:
        page = doc[page_no - 1]
        pix = page.get_pixmap(clip=pymupdf.Rect(*bbox), dpi=dpi)
        return pix.tobytes("png")
