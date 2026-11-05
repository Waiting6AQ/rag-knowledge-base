package com.ragadmin.common;

import org.assertj.core.api.ThrowableAssert.ThrowingCallable;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * ChatRateLimiter 单元测试：并发位、令牌桶、重复释放
 * 纯单元测试：直接 new，不启动 Spring 容器
 */
class ChatRateLimiterTest {

    /** 默认把 QPS 调高，避免干扰并发相关的用例 */
    private RateLimitProperties props(int maxConcurrent, int maxPerUser, long waitMillis) {
        RateLimitProperties p = new RateLimitProperties();
        p.setUserQps(100);
        p.setUserBurst(100);
        p.setGlobalQps(1000);
        p.setGlobalBurst(1000);
        p.setMaxConcurrent(maxConcurrent);
        p.setMaxConcurrentPerUser(maxPerUser);
        p.setWaitMillis(waitMillis);
        return p;
    }

    @Test
    @DisplayName("同一用户并发超过上限：第二个请求立即 429，释放后可再次获取")
    void perUserConcurrency() {
        ChatRateLimiter limiter = new ChatRateLimiter(props(8, 1, 10));

        ChatRateLimiter.Permit first = limiter.acquire(1L);
        assertTooMany(() -> limiter.acquire(1L));

        first.close();
        ChatRateLimiter.Permit second = limiter.acquire(1L);
        second.close();
    }

    @Test
    @DisplayName("全局并发满且等待超时：429，释放后可进入")
    void globalConcurrencyTimeout() {
        ChatRateLimiter limiter = new ChatRateLimiter(props(1, 1, 20));

        ChatRateLimiter.Permit first = limiter.acquire(1L);
        assertTooMany(() -> limiter.acquire(2L));

        first.close();
        ChatRateLimiter.Permit second = limiter.acquire(2L);
        second.close();
    }

    @Test
    @DisplayName("每用户 QPS：突发用完后 429")
    void userQpsLimit() {
        RateLimitProperties p = props(8, 1, 10);
        p.setUserQps(0);      // 不补充，只靠突发额度
        p.setUserBurst(2);
        ChatRateLimiter limiter = new ChatRateLimiter(p);

        limiter.acquire(1L).close();
        limiter.acquire(1L).close();

        assertTooMany(() -> limiter.acquire(1L));
    }

    @Test
    @DisplayName("全局 QPS：突发用完后 429")
    void globalQpsLimit() {
        RateLimitProperties p = props(8, 1, 10);
        p.setGlobalQps(0);
        p.setGlobalBurst(2);
        ChatRateLimiter limiter = new ChatRateLimiter(p);

        limiter.acquire(1L).close();
        limiter.acquire(2L).close();

        assertTooMany(() -> limiter.acquire(3L));
    }

    @Test
    @DisplayName("Permit 重复 close 不会多归还并发位")
    void doubleCloseIsSafe() {
        ChatRateLimiter limiter = new ChatRateLimiter(props(1, 1, 10));

        ChatRateLimiter.Permit permit = limiter.acquire(1L);
        permit.close();
        permit.close();   // 不应抛异常，也不应把信号量加爆

        // 全局只有 1 个位：如果被多还了，这里能同时拿到第 2 个
        ChatRateLimiter.Permit only = limiter.acquire(2L);
        assertTooMany(() -> limiter.acquire(3L));
        only.close();
    }

    private static void assertTooMany(ThrowingCallable callable) {
        assertThatThrownBy(callable)
                .isInstanceOfSatisfying(BusinessException.class,
                        e -> assertThat(e.getCode()).isEqualTo(429));
    }
}
