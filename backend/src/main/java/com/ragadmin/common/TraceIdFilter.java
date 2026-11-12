package com.ragadmin.common;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.UUID;

/**
 * 链路 ID 过滤器：每个请求分配一个 traceId
 *
 * 去向有三处：
 *   ① MDC —— 日志格式里的 %X{traceId} 从这儿取，Java 每条日志都带
 *   ② 响应头 X-Request-Id —— 前端报障时可以直接把这个 id 给过来
 *   ③ 出站请求头 X-Request-Id —— 由 RestClientConfig 的拦截器转发给 Python 引擎，
 *      引擎日志用同一个 id，两边 grep 同一个值就能串起整条链路
 *
 * 上游已经带了 X-Request-Id 就沿用（多跳网关场景），没有才自己生成。
 * 注意 MDC 是 ThreadLocal：SSE 在 sse- 线程池里跑，靠 AsyncConfig 的 TaskDecorator 复制过去。
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class TraceIdFilter extends OncePerRequestFilter {

    public static final String HEADER = "X-Request-Id";
    public static final String MDC_KEY = "traceId";

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String traceId = request.getHeader(HEADER);
        // 超长的一律当作无效，别让客户端往日志里塞垃圾
        if (traceId == null || traceId.isBlank() || traceId.length() > 64) {
            traceId = UUID.randomUUID().toString().replace("-", "").substring(0, 12);
        }
        MDC.put(MDC_KEY, traceId);
        response.setHeader(HEADER, traceId);
        try {
            chain.doFilter(request, response);
        } finally {
            MDC.remove(MDC_KEY);
        }
    }
}
