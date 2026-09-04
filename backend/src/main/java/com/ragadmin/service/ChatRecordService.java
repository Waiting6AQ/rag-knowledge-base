package com.ragadmin.service;

import com.ragadmin.mapper.ChatMessageMapper;
import com.ragadmin.mapper.ChatSessionMapper;
import com.ragadmin.model.ChatMessage;
import com.ragadmin.model.ChatSession;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 会话消息落库：多步写操作收进一个事务（要么全成功要么全回滚，不留半条记录）
 * 独立成 bean 的原因：@Transactional 依赖 Spring AOP 代理，ChatService 内部自调用会绕过代理导致注解失效
 */
@Service
@RequiredArgsConstructor
public class ChatRecordService {

    private static final String DEFAULT_TITLE = "新会话";

    private final ChatSessionMapper sessionMapper;
    private final ChatMessageMapper messageMapper;

    /** 一轮问答落库：用户消息 + AI 回复（带引用来源）+ 标题更新，同一事务保证原子性 */
    @Transactional
    public void saveExchange(ChatSession session, String userMsg, String reply, String sources) {
        saveMessage(session.getId(), "user", userMsg, null);
        saveMessage(session.getId(), "assistant", reply, sources);
        if (DEFAULT_TITLE.equals(session.getTitle())) {
            sessionMapper.updateTitle(session.getId(), truncate(userMsg));
        }
    }

    private void saveMessage(Long sessionId, String role, String content, String sources) {
        ChatMessage msg = new ChatMessage();
        msg.setSessionId(sessionId);
        msg.setRole(role);
        msg.setContent(content);
        msg.setSources(sources);
        messageMapper.insert(msg);
    }

    private String truncate(String s) {
        return s.length() > 80 ? s.substring(0, 80) : s;
    }
}
