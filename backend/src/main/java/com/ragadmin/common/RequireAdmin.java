package com.ragadmin.common;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 标在"整条接口只有管理员能调"的方法上，由 JwtInterceptor 统一校验
 *
 * 做成注解而不是按路径前缀拦：同一前缀下可能有不同权限要求的接口，
 * 注解能精确到方法，而且"要不要管理员"写在接口定义处，一眼可见
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface RequireAdmin {
}
