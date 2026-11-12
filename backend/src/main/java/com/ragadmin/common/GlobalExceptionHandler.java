package com.ragadmin.common;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.context.request.async.AsyncRequestNotUsableException;
import org.springframework.web.context.request.async.AsyncRequestTimeoutException;
import org.springframework.web.multipart.MaxUploadSizeExceededException;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.stream.Collectors;

/**
 * 全局异常处理：所有异常在这里统一转成 Result 结构，Controller 不再各自 try/catch
 */
@Slf4j
@RestControllerAdvice
@RequiredArgsConstructor
public class GlobalExceptionHandler {

    private final ObjectMapper objectMapper;

    /** 客户端已断开 / 异步超时（SSE 场景常见）：连接都断了，无需返回响应，静默处理避免次生错误 */
    @ExceptionHandler({AsyncRequestNotUsableException.class, AsyncRequestTimeoutException.class})
    public void handleAsyncNotUsable(Exception e) {
        log.debug("异步请求中断: {}", e.getMessage());
    }

    /** 上传超过 Java 侧大小限制 → 400 友好提示（20MB，与 AI 服务对齐） */
    @ExceptionHandler(MaxUploadSizeExceededException.class)
    public ResponseEntity<Result<Void>> handleMaxUpload(MaxUploadSizeExceededException e) {
        log.warn("上传超过大小限制: {}", e.getMessage());
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(Result.error(400, "文件超过 20MB 限制，请压缩后重新上传"));
    }

    /** 参数校验失败（@Valid 触发）→ 400 */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Result<Void>> handleValidation(MethodArgumentNotValidException e) {
        String msg = e.getBindingResult().getFieldErrors().stream()
                .map(FieldError::getDefaultMessage)
                .collect(Collectors.joining("；"));
        log.warn("参数校验失败: {}", msg);
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(Result.error(400, msg));
    }

    /**
     * 业务异常 → 携带自己的 code
     *
     * 直接写 response，不走内容协商：流式客户端可能只声明 Accept: text/event-stream，
     * 而限流的 429 是 JSON；交给消息转换器会因 Accept 不匹配再抛异常，最终变成 500。
     * 这里强制写 JSON，保证限流/业务错误一定能送达。
     */
    @ExceptionHandler(BusinessException.class)
    public void handleBusiness(BusinessException e, HttpServletResponse response) throws IOException {
        if (response.isCommitted()) {
            log.debug("响应已提交，无法写入业务错误: {}", e.getMessage());
            return;
        }
        // 429（限流）/ 503（AI 不可用）都走这里：记下 code 和原因，
        // 访问日志只到状态码，具体是"上一个问题还在处理中"还是"当前请求较多"要看这一行
        log.warn("业务异常 {}: {}", e.getCode(), e.getMessage());
        response.setStatus(e.getCode());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        objectMapper.writeValue(response.getWriter(), Result.error(e.getCode(), e.getMessage()));
    }

    /** 兜底：未知异常 → 500，不暴露内部细节 */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<Result<Void>> handleUnknown(Exception e) {
        log.error("未捕获异常", e);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(Result.error(500, "服务器内部错误"));
    }
}
