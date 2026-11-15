package com.ragadmin.config;

import com.ragadmin.common.TraceIdFilter;
import org.slf4j.MDC;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import org.springframework.http.client.ClientHttpRequestInterceptor;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

/**
 * 调用内部 AI 服务的 HTTP 客户端（RestClient：Spring 6.1+ 新同步客户端）
 * connectTimeout：TCP 建连上限（本地毫秒级，5s 宽裕）
 * readTimeout：两次读取间隔上限——60s 保证非流式等 LLM 完整回答（重试/降级可能超 30s）；
 *              流式生成若处于思考阶段，引擎每 10s 发一次 progress 心跳，不会误触发
 */
@Configuration
public class RestClientConfig {

    /**
     * 出站请求带上当前链路的 traceId，引擎日志用同一个 id，两边能对上。
     * 放在拦截器里而不是每个调用点手写：聊天、文档、FAQ、会话清理都自动覆盖。
     * 流式转发在 sse- 线程执行，MDC 由 AsyncConfig 的 TaskDecorator 带过来。
     */
    private static final ClientHttpRequestInterceptor TRACE_ID = (request, body, execution) -> {
        String traceId = MDC.get(TraceIdFilter.MDC_KEY);
        if (traceId != null) {
            request.getHeaders().set(TraceIdFilter.HEADER, traceId);
        }
        return execution.execute(request, body);
    };

    /** 主客户端（长超时）：聊天/文档等正常调用默认注入它；清理等 best-effort 场景用 cleanupRestClient */
    @Primary
    @Bean
    public RestClient aiRestClient() {
        return buildClient(5_000, 60_000);
    }

    /** best-effort 清理专用：引擎挂起/无响应时 3-5s 内放弃，不拖住用户请求（如删除会话时的引擎对话清理） */
    @Bean
    public RestClient cleanupRestClient() {
        return buildClient(3_000, 5_000);
    }

    private RestClient buildClient(int connectTimeout, int readTimeout) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(connectTimeout);
        factory.setReadTimeout(readTimeout);
        return RestClient.builder()
                .requestFactory(factory)
                .requestInterceptor(TRACE_ID)
                .build();
    }
}
