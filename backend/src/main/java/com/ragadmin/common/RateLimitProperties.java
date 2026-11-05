package com.ragadmin.common;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * 网关限流配置（application.yml 的 app.rate-limit.*）
 *
 * 默认值按「单实例 + 2 核」估算；压测后按实际吞吐调整。
 * 注意：这是单实例内存限流，多实例部署时全局限制会变成 N 倍。
 */
@Data
@Component
@ConfigurationProperties(prefix = "app.rate-limit")
public class RateLimitProperties {

    /** 每个用户每秒补充的令牌数（长期平均 QPS） */
    private int userQps = 3;

    /** 每个用户的桶容量（允许的短时突发） */
    private int userBurst = 6;

    /** 全局每秒补充的令牌数 */
    private int globalQps = 30;

    /** 全局桶容量 */
    private int globalBurst = 60;

    /** 全局同时在途的聊天请求上限 */
    private int maxConcurrent = 8;

    /** 每个用户同时在途的聊天请求上限（防双击 / 多标签页） */
    private int maxConcurrentPerUser = 1;

    /** 全局并发位爆满时，最多等多久（毫秒）；等不到返回 429 */
    private long waitMillis = 1500;
}
