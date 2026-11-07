"""
聊天接口并发压测

目的：
1. 验证并发闸门：并发数超过上限时，一部分请求应返回 429，而不是把服务拖慢
2. 验证许可释放：压测结束后，再发一个正常请求应该能成功（说明并发位没有泄漏）

用法：
    # 打引擎（默认，不需要登录）
    python scripts/load_test_chat.py
    python scripts/load_test_chat.py --concurrency 20

    # 打网关（需要登录；不传 token 就用账号密码登录）
    python scripts/load_test_chat.py \
        --url http://localhost:8081/api/chat/stream \
        --username admin --password 你的密码

    # 已经有 token 时直接传
    python scripts/load_test_chat.py --url ... --token eyJ...

说明：
- 打网关且所有请求用同一个 token 时，**每用户并发上限（默认 1）会先拦截**，
  只会看到 1 个 200、其余 429。这是预期行为。想测网关的「全局并发」，
  先把 application.yml 的 max-concurrent-per-user 临时调大（比如 20），
  测完改回 1。
- 打引擎没有每用户限制，20 并发下应看到约 max-concurrent 个 200，其余 429。
"""
import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# Windows 控制台默认 GBK，中文报错信息可能编码失败
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

DEFAULT_PROMPT = "用一句话回答：1+1 等于几？"


def login(base_url: str, username: str, password: str) -> str:
    """用账号密码换 JWT（网关的 /api/auth/login 不需要鉴权）"""
    login_url = urllib.parse.urljoin(base_url, "/api/auth/login")
    body = json.dumps({"username": username, "password": password}).encode("utf-8")
    req = urllib.request.Request(login_url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise SystemExit(f"登录失败 HTTP {e.code}: {detail}")
    except Exception as e:
        raise SystemExit(f"登录失败: {e}")
    token = (data.get("data") or {}).get("token")
    if not token:
        raise SystemExit(f"登录响应里没有 token: {data}")
    return token


def one_request(url: str, field: str, prompt: str, token: str | None, timeout: float):
    """发一条流式请求并读到流结束（读完才算释放并发位）"""
    body = json.dumps({field: prompt}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    # 正常客户端同时接受 SSE 和 JSON：成功时是 SSE 流，限流/报错时是 JSON。
    # 只写 text/event-stream 的话，服务端的内容协商找不到能把错误对象写成
    # SSE 的转换器，429 会被升级成 500。
    req.add_header("Accept", "text/event-stream, application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            lines = 0
            # 逐行读完 SSE：不解析内容，只确保流真正结束
            while True:
                line = resp.readline()
                if not line:
                    break
                lines += 1
            return status, time.perf_counter() - start, f"{lines} 行"
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:160]
        except Exception:
            pass
        return e.code, time.perf_counter() - start, detail
    except Exception as e:
        return "ERR", time.perf_counter() - start, repr(e)[:160]


def recovery_check(url: str, field: str, prompt: str, token: str | None, timeout: float):
    """压测后再发一条：能成功说明并发位已经归还，没有泄漏"""
    for attempt in range(3):
        status, elapsed, detail = one_request(url, field, prompt, token, timeout)
        if status == 200:
            return True, elapsed, detail
        time.sleep(2)   # 可能还有上一轮的长流在收尾，等两秒再试
    return False, elapsed, f"HTTP {status}: {detail}"


def main():
    parser = argparse.ArgumentParser(description="聊天接口并发压测（仅标准库）")
    # 用 127.0.0.1 而不是 localhost：Windows 上 localhost 会先解析到 IPv6 的 ::1，
    # 引擎只监听 IPv4，回退一次要多花约 2 秒，会污染单请求耗时
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/v1/chat/stream",
                        help="聊天流式接口地址（默认打 RAG 引擎）")
    parser.add_argument("--field", default="question", choices=["question", "message"],
                        help="请求体字段名：RAG 用 question，客服用 message")
    parser.add_argument("--concurrency", type=int, default=20, help="并发请求数")
    parser.add_argument("--timeout", type=float, default=180, help="单请求超时（秒）")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="压测用的短问题")
    parser.add_argument("--token", help="网关 JWT（不传则用账号密码登录）")
    parser.add_argument("--username", help="网关登录用户名")
    parser.add_argument("--password", help="网关登录密码")
    args = parser.parse_args()

    if args.concurrency <= 0:
        raise SystemExit("--concurrency 必须大于 0")

    token = args.token
    if token is None and args.username:
        if not args.password:
            raise SystemExit("传了 --username 就要同时传 --password")
        token = login(args.url, args.username, args.password)
        print("登录成功，已获取 token")

    print(f"目标: {args.url}")
    print(f"并发: {args.concurrency}，单请求超时: {args.timeout}s")
    print("开始……\n")

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(
            lambda _: one_request(args.url, args.field, args.prompt, token, args.timeout),
            range(args.concurrency),
        ))
    total = time.perf_counter() - started

    # 统计
    by_status: dict = {}
    for status, _, _ in results:
        by_status[status] = by_status.get(status, 0) + 1
    durations = [elapsed for status, elapsed, _ in results if status == 200]
    errors = [detail for status, _, detail in results if status != 200]

    print("结果：")
    for status, count in sorted(by_status.items(), key=lambda kv: str(kv[0])):
        print(f"  HTTP {status}: {count} 个")
    print(f"总耗时: {total:.2f}s")

    if durations:
        print(f"成功请求耗时: min {min(durations):.2f}s / "
              f"中位 {statistics.median(durations):.2f}s / max {max(durations):.2f}s")
    if errors:
        # 去重，避免 12 条一模一样的 429 刷屏
        uniq = list(dict.fromkeys(errors))
        print("失败示例：")
        for detail in uniq[:3]:
            print(f"  {detail}")

    print("\n恢复检查（压测后单发一条）：")
    ok, elapsed, detail = recovery_check(args.url, args.field, args.prompt, token, args.timeout)
    if ok:
        print(f"  ✅ 成功（{elapsed:.2f}s），并发位没有泄漏")
    else:
        print(f"  ❌ 仍然失败：{detail}")
        print("  可能原因：还有长流没结束，或许可泄漏。过几秒再跑一次确认。")

    # 退出码给 CI / 脚本用：恢复失败视为异常
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
