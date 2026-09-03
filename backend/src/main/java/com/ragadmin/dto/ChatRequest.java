package com.ragadmin.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class ChatRequest {

    /** RAG 协议：问题字段名是 question（与客服的 message 不同） */
    @NotBlank(message = "问题不能为空")
    private String question;

    /** 会话ID（数据库主键，来自 /api/sessions 列表）；不传则自动创建新会话 */
    @JsonProperty("session_id")
    private Long sessionId;
}
