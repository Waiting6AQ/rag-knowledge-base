package com.ragadmin.controller;

import com.ragadmin.common.Result;
import com.ragadmin.dto.DocumentListResponse;
import com.ragadmin.dto.DocumentUploadResponse;
import com.ragadmin.service.DocumentService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

/** 知识库文档管理（RAG 后台特色功能） */
@RestController
@RequestMapping("/api/documents")
@RequiredArgsConstructor
public class DocumentController {

    private final DocumentService documentService;

    @GetMapping
    public Result<DocumentListResponse> list() {
        return Result.ok(documentService.list());
    }

    @PostMapping("/upload")
    public Result<DocumentUploadResponse> upload(@RequestParam("file") MultipartFile file) {
        return Result.ok(documentService.upload(file));
    }

    @DeleteMapping("/{docId}")
    public Result<Void> delete(@PathVariable String docId) {
        documentService.delete(docId);
        return Result.ok();
    }
}
