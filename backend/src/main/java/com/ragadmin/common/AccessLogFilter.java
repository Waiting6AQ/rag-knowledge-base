package com.ragadmin.common;

import com.ragadmin.config.JwtInterceptor;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * 访问日志：每个请求一行（方法 路径 状态码 耗时 用户），4xx/5xx 打 WARN
 *
 * 流式接口（/api/chat/stream）这里只能记到"响应交给异步线程"为止的耗时（通常几毫秒），
 * 真实流时长在 ChatController 的 finally 里另记一行 —— 见那里的注释。
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)   // 在 TraceIdFilter 之内，保证日志能带上 traceId
public class AccessLogFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger("access");

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        if ("OPTIONS".equalsIgnoreCase(request.getMethod())) {
            chain.doFilter(request, response);   // CORS 预检不记
            return;
        }
        long start = System.nanoTime();
        try {
            chain.doFilter(request, response);
        } finally {
            long costMs = (System.nanoTime() - start) / 1_000_000;
            // 鉴权通过时由 JwtInterceptor 写入；登录接口没有用户
            Object userId = request.getAttribute(JwtInterceptor.ATTR_USER_ID);
            int status = response.getStatus();
            // 不记客户端 IP：nginx 的 access log 已经有真实 IP，且 IP 属于个人信息，不必在业务日志里再存一份
            Object[] args = {request.getMethod(), request.getRequestURI(), status, costMs,
                    userId == null ? "-" : userId};
            if (status >= 400) {
                log.warn("{} {} {} {}ms user={}", args);
            } else {
                log.info("{} {} {} {}ms user={}", args);
            }
        }
    }
}
