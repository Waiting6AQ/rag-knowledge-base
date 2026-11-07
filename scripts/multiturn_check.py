"""
多轮改写质量检查 —— 验证查询改写节点在"指代消解"上的表现

单轮评测集（rag_eval）测不到这项能力：每道题都是独立提问，没有指代。
这里用 5 段两轮对话，检查第二轮：

  1. rewritten_query 是否把"它 / 这笔钱 / 那病假"补全成了完整问题
  2. sources 是否命中了预期文档
  3. answer 是否覆盖了预期关键词

用法：

    # 默认跑 scripts/multiturn_cases.json
    python scripts/multiturn_check.py

    # 指定用例文件
    python scripts/multiturn_check.py --cases scripts/multiturn_cases.json
"""
import argparse
import json
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

_SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CASES = _SCRIPT_DIR / "multiturn_cases.json"


def _disp_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _disp_width(text))


def ask(url: str, question: str, conversation_id: str | None, timeout: float) -> dict:
    """调用非流式聊天接口，返回 ChatResponse"""
    body = {"question": question}
    if conversation_id:
        body["conversation_id"] = conversation_id
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise SystemExit(f"请求失败 HTTP {e.code}: {detail}")
    except Exception as e:
        raise SystemExit(f"请求失败: {e}")


def check_case(url: str, case: dict, timeout: float, index: int) -> bool:
    turns = case["turns"]
    if len(turns) != 2:
        print(f"{index}. {case['name']}\n   ⚠️ 用例必须正好两轮，跳过")
        return False

    first = ask(url, turns[0], None, timeout)
    second = ask(url, turns[1], first["conversation_id"], timeout)

    rewritten = second.get("rewritten_query") or ""
    sources = [s.get("source", "") for s in second.get("sources", [])]
    answer = second.get("answer", "")

    rewrite_ok = any(k in rewritten for k in case["rewrite_must"])
    doc_ok = any(case["expect_doc"] in s for s in sources)
    answer_ok = any(k in answer for k in case["answer_keywords"])
    passed = rewrite_ok and doc_ok and answer_ok

    print(f"\n{index}. {case['name']}")
    print(f"   第一轮: {turns[0]}")
    print(f"   第二轮: {turns[1]}")
    print(f"   改写  : {rewritten or '（未改写——原样返回）'}  "
          f"{'✓' if rewrite_ok else '✗ 期望包含 ' + ' / '.join(case['rewrite_must'])}")
    print(f"   来源  : {', '.join(sources) or '（无）'}  "
          f"{'✓' if doc_ok else '✗ 期望 ' + case['expect_doc']}")
    if answer_ok:
        print("   关键词: ✓")
    else:
        print(f"   关键词: ✗ 期望包含 {' / '.join(case['answer_keywords'])}")
        print(f"   回答片段: {answer[:120]}")
    print(f"   结论  : {'PASS' if passed else 'FAIL'}")
    return passed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="多轮改写质量检查：验证指代消解是否仍然正确")
    # 用 127.0.0.1 而不是 localhost：Windows 上 localhost 会先解析到 IPv6 的 ::1，
    # 引擎只监听 IPv4，回退一次要多花约 2 秒
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/v1/chat",
                        help="非流式聊天接口地址")
    parser.add_argument("--cases", default=str(DEFAULT_CASES),
                        help="用例 JSON 路径")
    parser.add_argument("--timeout", type=float, default=180, help="单请求超时（秒）")
    args = parser.parse_args()

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    if not cases:
        raise SystemExit("用例为空")

    print("=== 多轮改写质量检查 ===")
    print(f"目标: {args.url}")
    print(f"用例: {len(cases)} 段 × 2 轮")

    results = [
        check_case(args.url, case, args.timeout, i + 1)
        for i, case in enumerate(cases)
    ]
    passed = sum(results)

    header = f"{_pad('用例', 4)}{_pad('结果', 8)}"
    print(f"\n=== 汇总 ===")
    print(header + "说明")
    print("-" * 60)
    for i, (case, ok) in enumerate(zip(cases, results), start=1):
        print(f"{_pad(str(i), 4)}{_pad('PASS' if ok else 'FAIL', 8)}{case['name']}")

    print(f"\n通过 {passed}/{len(cases)}")
    sys.exit(0 if passed == len(cases) else 1)


if __name__ == "__main__":
    main()
