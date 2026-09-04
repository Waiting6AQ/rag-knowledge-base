package com.ragadmin.service;

import com.ragadmin.common.BusinessException;
import com.ragadmin.common.PageResult;
import com.ragadmin.dto.SessionDetail;
import com.ragadmin.mapper.ChatMessageMapper;
import com.ragadmin.mapper.ChatSessionMapper;
import com.ragadmin.model.ChatMessage;
import com.ragadmin.model.ChatSession;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestClient;

import java.util.List;
import java.util.UUID;

/**
 * 会话管理：业务侧自持记录（管理/审计视角），与 AI 服务内部状态解耦
 * 标题规则对齐 Python 侧：发消息时更新为最新消息前 80 字（Phase 3 实现）
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class SessionService {

    private static final String DEFAULT_TITLE = "新会话";

    private final ChatSessionMapper sessionMapper;
    private final ChatMessageMapper messageMapper;
    /** best-effort 清理专用客户端（3s/5s 超时），引擎挂起时不拖住用户请求 */
    @Qualifier("cleanupRestClient")
    private final RestClient cleanupRestClient;

    @Value("${app.ai-service-url}")
    private String aiServiceUrl;

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

    /** 删除：本地级联清理（同一事务）后通知 AI 服务清理其对话（checkpoint/元数据，引擎不可达时降级不阻塞） */
    @Transactional
    public void delete(Long userId, Long sessionId) {
        ChatSession session = getOwnedSession(userId, sessionId);
        messageMapper.deleteBySessionId(sessionId);
        sessionMapper.deleteById(sessionId);
        deleteEngineConversation(session.getConversationId());
    }

    /** 通知引擎删除对话：本地已删完，引擎失败只告警（孤儿数据由引擎侧容忍，不阻塞用户操作） */
    private void deleteEngineConversation(String conversationId) {
        if (conversationId == null) {
            return;
        }
        try {
            cleanupRestClient.delete()
                    .uri(aiServiceUrl + "/api/v1/conversations/" + conversationId)
                    .retrieve()
                    .toBodilessEntity();
        } catch (Exception e) {
            log.warn("AI 服务对话清理失败（已忽略，本地删除不受影响）: {}", e.getMessage());
        }
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
