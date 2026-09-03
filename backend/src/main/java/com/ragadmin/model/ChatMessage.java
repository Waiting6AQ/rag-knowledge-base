package com.ragadmin.model;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class ChatMessage {
    private Long id;
    private Long sessionId;
    /** user（用户提问） / assistant（AI 回答） */
    private String role;
    private String content;
    /** 引用来源 JSON 文本（assistant 消息）：[{"index":1,"source":"xx","content_preview":"..."}] */
    private String sources;
    private LocalDateTime createdAt;
}
