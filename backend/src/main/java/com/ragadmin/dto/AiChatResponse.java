package com.ragadmin.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;

/**
 * rag_engine（Python）返回的响应体
 * RAG 协议与客服不同：answer（回复）+ sources（引用来源列表），无 intent
 */
@Data
public class AiChatResponse {

    @JsonProperty("conversation_id")
    private String conversationId;

    private String answer;

    private List<SourceInfo> sources;

    private Double confidence;

    @JsonProperty("rewritten_query")
    private String rewrittenQuery;

    @JsonProperty("rag_used")
    private Boolean ragUsed;

    /** 引用来源：检索到的文档片段 */
    @Data
    public static class SourceInfo {
        private Integer index;
        private String source;
        @JsonProperty("content_preview")
        private String contentPreview;
    }
}
