package com.ragadmin.controller;

import com.ragadmin.common.Caller;
import com.ragadmin.common.Result;
import com.ragadmin.config.JwtInterceptor;
import com.ragadmin.dto.DocumentContentResponse;
import com.ragadmin.dto.DocumentListResponse;
import com.ragadmin.dto.DocumentUploadResponse;
import com.ragadmin.service.DocumentService;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
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
    public Result<DocumentListResponse> list(HttpServletRequest request) {
        return Result.ok(documentService.list(caller(request)));
    }

    @PostMapping("/upload")
    public Result<DocumentUploadResponse> upload(HttpServletRequest request,
                                                 @RequestParam("file") MultipartFile file) {
        return Result.ok(documentService.upload(file, caller(request)));
    }

    @GetMapping("/{docId}/content")
    public Result<DocumentContentResponse> content(@PathVariable String docId) {
        return Result.ok(documentService.getContent(docId));
    }

    /** 原始文件字节（非 JSON：前端在浏览器里重画 pdf/docx/xlsx 用） */
    @GetMapping("/{docId}/raw")
    public ResponseEntity<byte[]> raw(@PathVariable String docId) {
        return documentService.raw(docId);
    }

    @DeleteMapping("/{docId}")
    public Result<Void> delete(HttpServletRequest request, @PathVariable String docId) {
        documentService.delete(docId, caller(request));
        return Result.ok();
    }

    /** 当前登录者（拦截器已把身份解好放在 request 上） */
    private Caller caller(HttpServletRequest request) {
        return new Caller(
                (Long) request.getAttribute(JwtInterceptor.ATTR_USER_ID),
                (String) request.getAttribute(JwtInterceptor.ATTR_ROLE_CODE));
    }
}
