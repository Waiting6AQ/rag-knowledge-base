package com.ragadmin.controller;

import com.ragadmin.common.PageResult;
import com.ragadmin.common.Result;
import com.ragadmin.config.JwtInterceptor;
import com.ragadmin.dto.SessionDetail;
import com.ragadmin.model.ChatSession;
import com.ragadmin.service.SessionService;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/sessions")
@RequiredArgsConstructor
public class SessionController {

    private final SessionService sessionService;

    /** 创建会话（无 body：标题由消息驱动，对齐 Python 侧行为） */
    @PostMapping
    public Result<ChatSession> create(HttpServletRequest request) {
        Long userId = (Long) request.getAttribute(JwtInterceptor.ATTR_USER_ID);
        return Result.ok(sessionService.create(userId));
    }

    /** 分页列表（当前用户的会话，按更新时间倒序） */
    @GetMapping
    public Result<PageResult<ChatSession>> list(HttpServletRequest request,
                                                @RequestParam(defaultValue = "1") int page,
                                                @RequestParam(defaultValue = "10") int size) {
        Long userId = (Long) request.getAttribute(JwtInterceptor.ATTR_USER_ID);
        return Result.ok(sessionService.list(userId, page, size));
    }

    /** 详情：会话 + 消息列表 */
    @GetMapping("/{id}")
    public Result<SessionDetail> detail(HttpServletRequest request, @PathVariable Long id) {
        Long userId = (Long) request.getAttribute(JwtInterceptor.ATTR_USER_ID);
        return Result.ok(sessionService.detail(userId, id));
    }

    /** 删除会话（级联删消息） */
    @DeleteMapping("/{id}")
    public Result<Void> delete(HttpServletRequest request, @PathVariable Long id) {
        Long userId = (Long) request.getAttribute(JwtInterceptor.ATTR_USER_ID);
        sessionService.delete(userId, id);
        return Result.ok();
    }
}
