package com.ragadmin.model;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class ChatSession {
    private Long id;
    private Long userId;
    /** AI 服务侧会话ID（LangGraph checkpoint 关联键，Phase 3 转发时用） */
    private String conversationId;
    private String title;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
