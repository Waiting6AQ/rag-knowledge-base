package com.ragadmin.config;

import org.slf4j.MDC;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.task.TaskDecorator;

import java.util.Map;

/**
 * 异步线程的 MDC 传递
 *
 * 流式接口的 StreamingResponseBody 在 sse- 线程池里执行（applicationTaskExecutor），
 * 而 MDC 是 ThreadLocal，不复制的话：
 *   - 流里的错误日志没有 traceId
 *   - 转发给 Python 的 X-Request-Id 也拿不到值
 * 实测这就是"请求线程有 id、流线程没有"的原因。
 *
 * Spring Boot 会把容器里唯一的 TaskDecorator 自动应用到 applicationTaskExecutor，
 * MVC 的异步请求用的也是它，所以不用自己定义线程池。
 */
@Configuration
public class AsyncConfig {

    @Bean
    public TaskDecorator mdcTaskDecorator() {
        return runnable -> {
            // 提交时（请求线程）抓一份上下文快照
            Map<String, String> captured = MDC.getCopyOfContextMap();
            return () -> {
                Map<String, String> previous = MDC.getCopyOfContextMap();
                if (captured != null) {
                    MDC.setContextMap(captured);
                } else {
                    MDC.clear();
                }
                try {
                    runnable.run();
                } finally {
                    // 线程是复用的：跑完恢复原状，别把 traceId 漏给下一个任务
                    if (previous != null) {
                        MDC.setContextMap(previous);
                    } else {
                        MDC.clear();
                    }
                }
            };
        };
    }
}
