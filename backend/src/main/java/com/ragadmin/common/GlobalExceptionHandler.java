package com.ragadmin.common;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.context.request.async.AsyncRequestNotUsableException;
import org.springframework.web.context.request.async.AsyncRequestTimeoutException;
import org.springframework.web.multipart.MaxUploadSizeExceededException;

import java.util.stream.Collectors;

/**
 * 全局异常处理：所有异常在这里统一转成 Result 结构，Controller 不再各自 try/catch
 */
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    /** 客户端已断开 / 异步超时（SSE 场景常见）：连接都断了，无需返回响应，静默处理避免次生错误 */
    @ExceptionHandler({AsyncRequestNotUsableException.class, AsyncRequestTimeoutException.class})
    public void handleAsyncNotUsable(Exception e) {
        log.debug("异步请求中断: {}", e.getMessage());
    }

    /** 上传超过 Java 侧大小限制 → 400 友好提示（20MB，与 AI 服务对齐） */
    @ExceptionHandler(MaxUploadSizeExceededException.class)
    public ResponseEntity<Result<Void>> handleMaxUpload(MaxUploadSizeExceededException e) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(Result.error(400, "文件超过 20MB 限制，请压缩后重新上传"));
    }

    /** 参数校验失败（@Valid 触发）→ 400 */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Result<Void>> handleValidation(MethodArgumentNotValidException e) {
        String msg = e.getBindingResult().getFieldErrors().stream()
                .map(FieldError::getDefaultMessage)
                .collect(Collectors.joining("；"));
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(Result.error(400, msg));
    }

    /** 业务异常 → 携带自己的 code */
    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<Result<Void>> handleBusiness(BusinessException e) {
        return ResponseEntity.status(e.getCode()).body(Result.error(e.getCode(), e.getMessage()));
    }

    /** 兜底：未知异常 → 500，不暴露内部细节 */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<Result<Void>> handleUnknown(Exception e) {
        log.error("未捕获异常", e);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(Result.error(500, "服务器内部错误"));
    }
}
