package com.ragadmin.common;

import lombok.Getter;

/**
 * 业务异常：Service 层抛出，由 GlobalExceptionHandler 统一转成 Result
 */
@Getter
public class BusinessException extends RuntimeException {

    private final int code;

    public BusinessException(int code, String message) {
        super(message);
        this.code = code;
    }

    /** 默认 400 参数/业务错误 */
    public static BusinessException badRequest(String message) {
        return new BusinessException(400, message);
    }
}
