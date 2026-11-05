package com.ragadmin.controller;

import com.ragadmin.common.ChatRateLimiter;
import com.ragadmin.common.Result;
import com.ragadmin.config.JwtInterceptor;
import com.ragadmin.dto.ChatRequest;
import com.ragadmin.dto.ChatResponse;
import com.ragadmin.service.ChatService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

@RestController
@RequestMapping("/api/chat")
@RequiredArgsConstructor
public class ChatController {

    private final ChatService chatService;
    private final ChatRateLimiter rateLimiter;

    /** 聊天：转发 rag_engine，落库，返回 AI 回复 */
    @PostMapping
    public Result<ChatResponse> chat(HttpServletRequest request,
                                     @Valid @RequestBody ChatRequest req) {
        Long userId = (Long) request.getAttribute(JwtInterceptor.ATTR_USER_ID);
        // 限流闸门：拿不到许可抛 429，由 GlobalExceptionHandler 统一转成 JSON
        try (ChatRateLimiter.Permit ignored = rateLimiter.acquire(userId)) {
            return Result.ok(chatService.chat(userId, req));
        }
    }

    /** 流式聊天：原样透传 Python SSE 流（打字机效果），流结束后落库 */
    @PostMapping("/stream")
    public StreamingResponseBody stream(HttpServletRequest request, HttpServletResponse response,
                                        @Valid @RequestBody ChatRequest req) {
        // 提示反向代理（Nginx 等）不要缓冲该响应，保证 token 实时到达
        response.setHeader("X-Accel-Buffering", "no");
        Long userId = (Long) request.getAttribute(JwtInterceptor.ATTR_USER_ID);

        // 许可必须在流开始前拿到：拿不到时还能正常返回 429 JSON；
        // 等流开始后再拒绝，HTTP 状态码已经发出去了，前端只会看到半截流。
        ChatRateLimiter.Permit permit = rateLimiter.acquire(userId);
        try {
            StreamingResponseBody body = chatService.chatStream(userId, req);
            // 成功路径才把响应类型定成 SSE。
            // 不能写在 @PostMapping 的 produces 上：限流 429 要返回 JSON，
            // 映射级 produces 会逼着异常处理器用 event-stream 写 Result，写不出去变 500。
            response.setContentType(MediaType.TEXT_EVENT_STREAM_VALUE);
            return outputStream -> {
                try {
                    body.writeTo(outputStream);
                } finally {
                    // 正常结束、AI 报错、客户端断开都会走到这里
                    permit.close();
                }
            };
        } catch (RuntimeException e) {
            // 构造流之前就失败（建会话等）：立刻归还许可再抛
            permit.close();
            throw e;
        }
    }
}
