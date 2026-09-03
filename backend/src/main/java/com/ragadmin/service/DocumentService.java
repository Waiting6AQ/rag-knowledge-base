package com.ragadmin.service;

import com.ragadmin.common.BusinessException;
import com.ragadmin.dto.DocumentListResponse;
import com.ragadmin.dto.DocumentUploadResponse;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;

/**
 * 文档管理：调 rag_engine 文档 API（业务侧只做转发视图）
 * 上传走网关接收 → 流式转发（文件不落盘，仅存 Python 侧一份）
 * Python 的错误语义（409 重复文件 / 413 超限 / 400 类型错误，detail 含具体信息）透传给前端
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DocumentService {

    private final RestClient restClient;
    private final ObjectMapper objectMapper;

    @Value("${app.ai-service-url}")
    private String aiServiceUrl;

    /** 文档列表（只读视图） */
    public DocumentListResponse list() {
        return restClient.get()
                .uri(aiServiceUrl + "/api/v1/documents/")
                .retrieve()
                .body(DocumentListResponse.class);
    }

    /** 删除文档（级联删除向量索引） */
    public void delete(String docId) {
        try {
            restClient.delete()
                    .uri(aiServiceUrl + "/api/v1/documents/" + docId)
                    .retrieve()
                    .toBodilessEntity();
        } catch (HttpClientErrorException e) {
            // 透传 Python 的错误（如 404 文档不存在）
            throw new BusinessException(e.getStatusCode().value(), extractDetail(e));
        } catch (ResourceAccessException e) {
            log.warn("AI 服务不可达: {}", e.getMessage());
            throw new BusinessException(503, "AI 服务暂时不可用，请稍后再试");
        }
    }

    /** 上传文档：Java 接收 multipart → 流式转发 rag_engine（解析/分块/索引都在 Python 侧） */
    public DocumentUploadResponse upload(MultipartFile file) {
        if (file.isEmpty()) {
            throw BusinessException.badRequest("文件不能为空");
        }
        try {
            // multipart 转发：参数名必须与 rag_engine 的 UploadFile 参数一致（file）
            // 注：不用 InputStreamResource——HttpURLConnection 发送前要预读算 Content-Length，
            //     流只能读一次会抛异常；ByteArrayResource（20MB 上限下内存可控）最可靠
            ByteArrayResource resource = new ByteArrayResource(file.getBytes()) {
                @Override
                public String getFilename() {
                    return file.getOriginalFilename();
                }
            };
            MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
            body.add("file", resource);

            return restClient.post()
                    .uri(aiServiceUrl + "/api/v1/documents/upload")
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(body)
                    .retrieve()
                    .body(DocumentUploadResponse.class);
        } catch (HttpClientErrorException e) {
            // 透传 Python 的错误语义：409 文件内容重复（detail 含文件名）、413 超限、400 类型错误
            String detail = extractDetail(e);
            log.warn("上传被 AI 服务拒绝 ({}): {}", e.getStatusCode().value(), detail);
            throw new BusinessException(e.getStatusCode().value(), detail);
        } catch (IOException e) {
            log.error("读取上传文件失败", e);
            throw BusinessException.badRequest("文件读取失败");
        } catch (ResourceAccessException e) {
            log.warn("AI 服务不可达: {}", e.getMessage());
            throw new BusinessException(503, "AI 服务暂时不可用，请稍后再试");
        }
    }

    /** 从 Python 的错误响应体 {"detail": "..."} 提取消息 */
    private String extractDetail(HttpClientErrorException e) {
        try {
            String body = e.getResponseBodyAsString();
            if (body == null || body.isBlank()) {
                return e.getMessage();
            }
            return objectMapper.readTree(body).path("detail").asText(e.getMessage());
        } catch (Exception ex) {
            return e.getMessage();
        }
    }
}
