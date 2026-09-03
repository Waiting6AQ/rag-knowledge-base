package com.ragadmin.dto;

import com.ragadmin.model.ChatMessage;
import com.ragadmin.model.ChatSession;
import lombok.AllArgsConstructor;
import lombok.Data;

import java.util.List;

/** 会话详情响应：会话信息 + 消息列表（消息在 Phase 3 接入 AI 后产生） */
@Data
@AllArgsConstructor
public class SessionDetail {
    private ChatSession session;
    private List<ChatMessage> messages;
}
