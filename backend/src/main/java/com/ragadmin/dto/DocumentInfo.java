package com.ragadmin.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

/** 文档列表项（来自 rag_engine 文档 API） */
@Data
public class DocumentInfo {

    @JsonProperty("doc_id")
    private String docId;

    private String filename;

    @JsonProperty("file_type")
    private String fileType;

    @JsonProperty("chunk_count")
    private Integer chunkCount;

    @JsonProperty("upload_time")
    private String uploadTime;
}
