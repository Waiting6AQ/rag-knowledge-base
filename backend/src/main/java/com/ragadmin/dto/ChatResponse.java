package com.ragadmin.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Data;

import java.util.List;

/** Java 网关返回给前端的聊天响应（RAG 版：带引用来源） */
@Data
@AllArgsConstructor
public class ChatResponse {

    /** 会话ID（数据库主键），前端下次对话带上它继续 */
    @JsonProperty("session_id")
    private Long sessionId;

    private String answer;

    /** 引用来源（检索到的文档片段），RAG 特色 */
    private List<AiChatResponse.SourceInfo> sources;

    private double confidence;

    @JsonProperty("rag_used")
    private boolean ragUsed;
}
