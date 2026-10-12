package com.ragadmin.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

/** 文档全文（来自 rag_engine 文档 API，供前端点开查看） */
@Data
public class DocumentContentResponse {

    @JsonProperty("doc_id")
    private String docId;

    private String filename;

    @JsonProperty("file_type")
    private String fileType;

    private String content;

    /** 正文是否因超长被截断 */
    private Boolean truncated;
}
