package com.ragadmin.service;

import com.ragadmin.common.BusinessException;
import com.ragadmin.common.PageResult;
import com.ragadmin.dto.SessionDetail;
import com.ragadmin.mapper.ChatMessageMapper;
import com.ragadmin.mapper.ChatSessionMapper;
import com.ragadmin.model.ChatMessage;
import com.ragadmin.model.ChatSession;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.UUID;

/**
 * 会话管理：业务侧自持记录（管理/审计视角），与 AI 服务内部状态解耦
 * 标题规则对齐 Python 侧：发消息时更新为最新消息前 80 字（Phase 3 实现）
 */
@Service
@RequiredArgsConstructor
public class SessionService {

    private static final String DEFAULT_TITLE = "新会话";

    private final ChatSessionMapper sessionMapper;
    private final ChatMessageMapper messageMapper;

    /** 创建会话：conversation_id 由业务侧生成（UUID），Phase 3 转发时传给 AI 服务 */
    public ChatSession create(Long userId) {
        ChatSession session = new ChatSession();
        session.setUserId(userId);
        session.setConversationId(UUID.randomUUID().toString());
        session.setTitle(DEFAULT_TITLE);
        sessionMapper.insert(session);
        return session;
    }

    /** 分页列表：只返回当前用户的会话（归属过滤在 SQL 里） */
    public PageResult<ChatSession> list(Long userId, int page, int size) {
        int offset = (page - 1) * size;
        List<ChatSession> list = sessionMapper.selectPage(userId, offset, size);
        long total = sessionMapper.countByUser(userId);
        return new PageResult<>(total, list);
    }

    /** 详情：校验归属，返回会话 + 消息 */
    public SessionDetail detail(Long userId, Long sessionId) {
        ChatSession session = getOwnedSession(userId, sessionId);
        List<ChatMessage> messages = messageMapper.findBySessionId(sessionId);
        return new SessionDetail(session, messages);
    }

    /** 删除：校验归属，级联清理消息，防止孤儿数据 */
    public void delete(Long userId, Long sessionId) {
        getOwnedSession(userId, sessionId);
        messageMapper.deleteBySessionId(sessionId);
        sessionMapper.deleteById(sessionId);
    }

    /** 校验会话存在且属于当前用户，返回会话（跨用户访问返回 403） */
    public ChatSession getOwnedSession(Long userId, Long sessionId) {
        ChatSession session = sessionMapper.findById(sessionId);
        if (session == null) {
            throw BusinessException.badRequest("会话不存在");
        }
        if (!session.getUserId().equals(userId)) {
            throw new BusinessException(403, "无权访问该会话");
        }
        return session;
    }
}
