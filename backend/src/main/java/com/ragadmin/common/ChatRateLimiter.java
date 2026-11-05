package com.ragadmin.common;

import org.springframework.stereotype.Component;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * 聊天请求的网关级并发闸门
 *
 * 一个请求要依次通过两道闸门：
 *   ① 每用户并发（防重复提交，满了立即拒绝）
 *   ② 全局并发（信号量，最多等 waitMillis）
 *
 * 为什么只限并发、不做 QPS：
 *   聊天是秒级长请求，用户串行发送时的速率远低于常见的 QPS 阈值；
 *   真正会压垮系统的是「同时有多少个流在跑」，并发闸门才是有效约束。
 *
 * 任何一道失败都抛 429；已经占到的并发位会归还。
 *
 * 单实例有效：信号量在 JVM 内存里。部署多个网关实例时，
 * 全局限制会变成 N 倍；集群级限流需要换成 Redis 或放到网关/代理层。
 */
@Component
public class ChatRateLimiter {

    private final RateLimitProperties props;
    private final Semaphore globalConcurrent;
    /**
     * 每个用户的状态。key 是用户 id，数量受用户表限制，
     * 单实例内存里保留一份很小的对象，不做淘汰。
     */
    private final ConcurrentHashMap<Long, UserState> users = new ConcurrentHashMap<>();

    public ChatRateLimiter(RateLimitProperties props) {
        this.props = props;
        this.globalConcurrent = new Semaphore(props.getMaxConcurrent(), false);
    }

    /**
     * 获取一个许可。调用方必须在请求结束时 close()：
     * 普通请求用 try-with-resources，流式请求放在 StreamingResponseBody 的 finally 里。
     */
    public Permit acquire(Long userId) {
        UserState user = users.computeIfAbsent(userId, id -> new UserState(props));

        // ① 每用户并发：双击 / 多标签页的第二个请求直接拒绝，不占全局队列
        if (!user.inFlight.tryAcquire()) {
            throw tooMany("上一个问题还在处理中");
        }

        boolean acquired = false;
        try {
            // ② 全局并发：短暂排队，吸收一瞬间的突发
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
                user.inFlight.release();
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

    /** 每个用户的状态：自己的并发位 */
    private static final class UserState {
        private final Semaphore inFlight;

        private UserState(RateLimitProperties props) {
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
