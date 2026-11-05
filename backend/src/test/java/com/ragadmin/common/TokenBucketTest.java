package com.ragadmin.common;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.concurrent.atomic.AtomicLong;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * TokenBucket 单元测试：用可控时钟验证补充速率，不 sleep
 */
class TokenBucketTest {

    @Test
    @DisplayName("突发：容量内的请求全部通过，超出后拒绝")
    void burstCapacity() {
        AtomicLong clock = new AtomicLong();
        TokenBucket bucket = new TokenBucket(3, 0, clock::get);

        assertThat(bucket.tryAcquire()).isTrue();
        assertThat(bucket.tryAcquire()).isTrue();
        assertThat(bucket.tryAcquire()).isTrue();
        assertThat(bucket.tryAcquire()).isFalse();
    }

    @Test
    @DisplayName("按时间补充：前进 1 秒补 2 个")
    void refillByTime() {
        AtomicLong clock = new AtomicLong();
        TokenBucket bucket = new TokenBucket(2, 2, clock::get);

        assertThat(bucket.tryAcquire()).isTrue();
        assertThat(bucket.tryAcquire()).isTrue();
        assertThat(bucket.tryAcquire()).isFalse();

        clock.addAndGet(1_000_000_000L);   // 前进 1 秒
        assertThat(bucket.tryAcquire()).isTrue();
        assertThat(bucket.tryAcquire()).isTrue();
        assertThat(bucket.tryAcquire()).isFalse();
    }

    @Test
    @DisplayName("补充不超过桶容量")
    void refillCappedAtCapacity() {
        AtomicLong clock = new AtomicLong();
        TokenBucket bucket = new TokenBucket(2, 100, clock::get);

        clock.addAndGet(10_000_000_000L);   // 前进 10 秒，理论补 1000 个
        assertThat(bucket.remainingTokens()).isEqualTo(2.0);
    }
}
