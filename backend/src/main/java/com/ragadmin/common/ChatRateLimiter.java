package com.ragadmin.common;

import org.springframework.stereotype.Component;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * 聊天请求的网关级限流：令牌桶（QPS）+ 信号量（并发）
 *
 * 一个请求要依次通过四道闸门：
 *   ① 每用户并发（防重复提交，满了立即拒绝）
 *   ② 每用户 QPS（令牌桶）
 *   ③ 全局 QPS（令牌桶）
 *   ④ 全局并发（信号量，最多等 waitMillis）
 *
 * 任何一道失败都抛 429；已经占到的并发位会归还，令牌不退还
 * （请求确实来过，算一次流量）。
 *
 * 单实例有效：令牌桶和信号量都在 JVM 内存里。部署多个网关实例时，
 * 全局限制会变成 N 倍；集群级限流需要换成 Redis + Lua。
 */
@Component
public class ChatRateLimiter {

    private final RateLimitProperties props;
    private final TokenBucket globalBucket;
    private final Semaphore globalConcurrent;
    /**
     * 每个用户的状态。key 是用户 id，数量受用户表限制，
     * 单实例内存里保留一份很小的对象，不做淘汰。
     */
    private final ConcurrentHashMap<Long, UserState> users = new ConcurrentHashMap<>();

    public ChatRateLimiter(RateLimitProperties props) {
        this.props = props;
        this.globalBucket = new TokenBucket(props.getGlobalBurst(), props.getGlobalQps());
        this.globalConcurrent = new Semaphore(props.getMaxConcurrent(), false);
    }

    /**
     * 获取一个许可。调用方必须在请求结束时 close()：
     * 普通请求用 try-with-resources，流式请求放在 StreamingResponseBody 的 finally 里。
     */
    public Permit acquire(Long userId) {
        UserState user = users.computeIfAbsent(userId, id -> new UserState(props));

        // ① 每用户并发：双击 / 多标签页的第二个请求直接拒绝，不占队列
        if (!user.inFlight.tryAcquire()) {
            throw tooMany("上一个问题还在处理中");
        }

        boolean acquired = false;
        try {
            // ② 每用户 QPS
            if (!user.bucket.tryAcquire()) {
                throw tooMany("请求过于频繁");
            }
            // ③ 全局 QPS
            if (!globalBucket.tryAcquire()) {
                throw tooMany("系统繁忙");
            }
            // ④ 全局并发：短暂排队，吸收一瞬间的突发
            if (!globalConcurrent.tryAcquire(props.getWaitMillis(), TimeUnit.MILLISECONDS)) {
                throw tooMany("当前请求较多");
            }
            acquired = true;
            return new Permit(this, user);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new BusinessException(503, "请求被中断，请重试");
        } finally {
            if (!acquired) {
                user.inFlight.release();   // 归还 ①；②③ 的令牌不退还
            }
        }
    }

    private void release(UserState user) {
        user.inFlight.release();
        globalConcurrent.release();
    }

    private BusinessException tooMany(String reason) {
        return new BusinessException(429, reason + "，请稍后再试");
    }

    /** 每个用户的状态：自己的令牌桶 + 自己的并发位 */
    private static final class UserState {
        private final TokenBucket bucket;
        private final Semaphore inFlight;

        private UserState(RateLimitProperties props) {
            this.bucket = new TokenBucket(props.getUserBurst(), props.getUserQps());
            this.inFlight = new Semaphore(props.getMaxConcurrentPerUser(), false);
        }
    }

    /**
     * 许可凭证：close() 归还两个并发位。
     * AtomicBoolean 防重复 close（try-with-resources 和手动 finally 都写时不会多还）。
     */
    public static final class Permit implements AutoCloseable {

        private final ChatRateLimiter limiter;
        private final UserState user;
        private final AtomicBoolean closed = new AtomicBoolean(false);

        private Permit(ChatRateLimiter limiter, UserState user) {
            this.limiter = limiter;
            this.user = user;
        }

        @Override
        public void close() {
            if (closed.compareAndSet(false, true)) {
                limiter.release(user);
            }
        }
    }
}
