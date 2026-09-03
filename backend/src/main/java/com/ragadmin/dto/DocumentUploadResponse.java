package com.ragadmin.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

/** 文档上传结果（来自 rag_engine 文档 API） */
@Data
public class DocumentUploadResponse {

    @JsonProperty("doc_id")
    private String docId;

    private String filename;

    @JsonProperty("file_type")
    private String fileType;

    @JsonProperty("chunk_count")
    private Integer chunkCount;

    private Boolean renamed;

    private String status;
}
