package com.ragadmin.common;

import java.util.function.LongSupplier;

/**
 * 令牌桶：控制「每秒进来多少请求」
 *
 * 桶容量 capacity，每秒补充 refillPerSecond 个令牌；每个请求消耗 1 个。
 * 桶满后不再补充，所以允许短时突发（一次性最多 capacity 个）。
 *
 * 线程安全：补充 + 扣减在同一个 synchronized 里完成。锁只覆盖几个字段的
 * 算术运算，不涉及 IO，不会成为瓶颈。
 */
public class TokenBucket {

    private final double capacity;
    private final double refillPerNano;
    private final LongSupplier nanoClock;

    private double tokens;
    private long lastRefillNanos;

    public TokenBucket(double capacity, double refillPerSecond) {
        this(capacity, refillPerSecond, System::nanoTime);
    }

    /** 测试用：注入可控时钟，避免真的 sleep */
    TokenBucket(double capacity, double refillPerSecond, LongSupplier nanoClock) {
        if (capacity <= 0) {
            throw new IllegalArgumentException("capacity 必须大于 0");
        }
        this.capacity = capacity;
        this.refillPerNano = Math.max(refillPerSecond, 0) / 1_000_000_000.0;
        this.nanoClock = nanoClock;
        this.tokens = capacity;
        this.lastRefillNanos = nanoClock.getAsLong();
    }

    /** 尝试取一个令牌；桶空返回 false（不阻塞、不排队） */
    public synchronized boolean tryAcquire() {
        refill();
        if (tokens >= 1.0) {
            tokens -= 1.0;
            return true;
        }
        return false;
    }

    /** 当前令牌数（测试 / 观测用） */
    synchronized double remainingTokens() {
        refill();
        return tokens;
    }

    private void refill() {
        long now = nanoClock.getAsLong();
        long elapsed = now - lastRefillNanos;
        if (elapsed <= 0) {
            return;
        }
        lastRefillNanos = now;
        if (refillPerNano > 0) {
            // 无论隔了多久，最多补到桶容量，不能无限累积
            tokens = Math.min(capacity, tokens + elapsed * refillPerNano);
        }
    }
}
