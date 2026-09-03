package com.ragadmin.dto;

import lombok.Data;

import java.util.List;

@Data
public class DocumentListResponse {
    private long total;
    private List<DocumentInfo> documents;
}
