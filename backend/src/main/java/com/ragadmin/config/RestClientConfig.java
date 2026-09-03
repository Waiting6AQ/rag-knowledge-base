package com.ragadmin.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

/**
 * 调用内部 AI 服务的 HTTP 客户端（RestClient：Spring 6.1+ 新同步客户端）
 * connectTimeout：TCP 建连上限（本地毫秒级，5s 宽裕）
 * readTimeout：两次读取间隔上限——60s 保证非流式等 LLM 完整回答（重试/降级可能超 30s）；
 *              流式场景 Python 持续发 progress 事件（心跳），不会误触发
 */
@Configuration
public class RestClientConfig {

    @Bean
    public RestClient aiRestClient() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5_000);
        factory.setReadTimeout(60_000);
        return RestClient.builder().requestFactory(factory).build();
    }
}
