package com.ragadmin.common;

import lombok.Data;

/**
 * 统一响应结构：{code, message, data}
 * code: 200 成功 / 400 参数错误 / 401 未认证 / 403 无权限 / 500 服务器错误
 */
@Data
public class Result<T> {

    private int code;
    private String message;
    private T data;

    public static <T> Result<T> ok(T data) {
        Result<T> r = new Result<>();
        r.code = 200;
        r.message = "success";
        r.data = data;
        return r;
    }

    public static Result<Void> ok() {
        return ok(null);
    }

    public static <T> Result<T> error(int code, String message) {
        Result<T> r = new Result<>();
        r.code = code;
        r.message = message;
        return r;
    }
}
