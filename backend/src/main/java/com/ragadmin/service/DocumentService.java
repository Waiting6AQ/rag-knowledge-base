package com.ragadmin.service;

import com.ragadmin.common.BusinessException;
import com.ragadmin.common.Caller;
import com.ragadmin.dto.DocumentContentResponse;
import com.ragadmin.dto.DocumentInfo;
import com.ragadmin.dto.DocumentListResponse;
import com.ragadmin.dto.DocumentUploadResponse;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
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
 *
 * 权限：认证和"是不是管理员"都在这一层（JWT + 角色），引擎没有用户体系，
 * 只接收这里注入的身份、记下文档归属
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DocumentService {

    private final RestClient restClient;
    private final ObjectMapper objectMapper;

    @Value("${app.ai-service-url}")
    private String aiServiceUrl;

    /** 文档列表（只读视图）：顺手标出每条当前用户能不能删，前端不用再复述一遍规则 */
    public DocumentListResponse list(Caller caller) {
        DocumentListResponse resp;
        try {
            resp = restClient.get()
                    .uri(aiServiceUrl + "/api/v1/documents/")
                    .retrieve()
                    .body(DocumentListResponse.class);
        } catch (ResourceAccessException e) {
            // 引擎不可达：与 delete/upload 及 ChatService 一致的降级（友好提示而非 500）
            log.warn("AI 服务不可达: {}", e.getMessage());
            throw new BusinessException(503, "AI 服务暂时不可用，请稍后再试");
        }

        // 引擎只认归属，不管角色：管理员能删所有文档这条规则留在这里（只有这层知道角色）
        if (resp != null && resp.getDocuments() != null) {
            for (DocumentInfo d : resp.getDocuments()) {
                d.setCanDelete(caller.isAdmin() || caller.userId().toString().equals(d.getUploadedBy()));
            }
        }
        return resp;
    }

    /** 读取文档全文（供前端点开引用来源 / 文档列表时查看） */
    public DocumentContentResponse getContent(String docId) {
        try {
            return restClient.get()
                    .uri(aiServiceUrl + "/api/v1/documents/" + docId + "/content")
                    .retrieve()
                    .body(DocumentContentResponse.class);
        } catch (HttpClientErrorException e) {
            // 透传 Python 的错误语义：404 文档不存在 / 410 原始文件已不在服务器上
            throw new BusinessException(e.getStatusCode().value(), extractDetail(e));
        } catch (ResourceAccessException e) {
            log.warn("AI 服务不可达: {}", e.getMessage());
            throw new BusinessException(503, "AI 服务暂时不可用，请稍后再试");
        }
    }

    /**
     * 原始文件字节 + 类型（前端按格式渲染原文时用）
     *
     * 网关里唯一非 JSON 的返回：前端要在浏览器里重画 pdf/docx/xlsx，必须拿到原始字节。
     * 前端带 token 取回后转成 blob URL，所以不会暴露一个无鉴权的文件地址。
     */
    public ResponseEntity<byte[]> raw(String docId) {
        try {
            ResponseEntity<byte[]> resp = restClient.get()
                    .uri(aiServiceUrl + "/api/v1/documents/" + docId + "/raw")
                    .retrieve()
                    .toEntity(byte[].class);
            // 把引擎给的 Content-Type 原样带出去，前端才知道这是 pdf 还是 xlsx
            return ResponseEntity.ok()
                    .contentType(resp.getHeaders().getContentType())
                    .body(resp.getBody());
        } catch (HttpClientErrorException e) {
            // 透传 Python 的错误语义：404 文档不存在 / 410 原始文件已不在服务器上
            throw new BusinessException(e.getStatusCode().value(), extractDetail(e));
        } catch (ResourceAccessException e) {
            log.warn("AI 服务不可达: {}", e.getMessage());
            throw new BusinessException(503, "AI 服务暂时不可用，请稍后再试");
        }
    }

    /** 删除文档（级联删除向量索引）；非本人上传且无权删任意文档的，由引擎拒绝，这里透传 403 */
    public void delete(String docId, Caller caller) {
        try {
            restClient.delete()
                    .uri(aiServiceUrl + "/api/v1/documents/" + docId)
                    .header(Caller.HEADER_USER_ID, caller.userId().toString())
                    .header(Caller.HEADER_CAN_DELETE_ANY, String.valueOf(caller.isAdmin()))
                    .retrieve()
                    .toBodilessEntity();
        } catch (HttpClientErrorException e) {
            // 透传 Python 的错误（404 文档不存在 / 403 无权删除）
            throw new BusinessException(e.getStatusCode().value(), extractDetail(e));
        } catch (ResourceAccessException e) {
            log.warn("AI 服务不可达: {}", e.getMessage());
            throw new BusinessException(503, "AI 服务暂时不可用，请稍后再试");
        }
    }

    /** 上传文档：Java 接收 multipart → 流式转发 rag_engine（解析/分块/索引都在 Python 侧） */
    public DocumentUploadResponse upload(MultipartFile file, Caller caller) {
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
                    // 归属由引擎记下：之后靠它判断"是不是本人传的"
                    .header(Caller.HEADER_USER_ID, caller.userId().toString())
                    .header(Caller.HEADER_CAN_DELETE_ANY, String.valueOf(caller.isAdmin()))
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
