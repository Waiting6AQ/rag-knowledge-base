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

    /** 上传者 ID（改造前上传的文档没有这个值） */
    @JsonProperty("uploaded_by")
    private String uploadedBy;

    /** 当前用户能否删除：本人上传的，或自己是管理员。由后端算好，前端只管显示 */
    @JsonProperty("can_delete")
    private Boolean canDelete;
}
