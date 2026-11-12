package com.ragadmin.config;

import com.ragadmin.common.Caller;
import com.ragadmin.common.RequireAdmin;
import com.ragadmin.common.Result;
import com.ragadmin.util.JwtUtil;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.jsonwebtoken.Claims;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.HandlerInterceptor;

import java.nio.charset.StandardCharsets;

/**
 * JWT 拦截器：校验 Authorization: Bearer <token>
 * 通过后把 userId / roleCode 放入 request 属性，Controller 直接取；
 * 带 @RequireAdmin 的方法在这里统一判权限
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class JwtInterceptor implements HandlerInterceptor {

    public static final String ATTR_USER_ID = "userId";
    public static final String ATTR_ROLE_CODE = "roleCode";

    private final JwtUtil jwtUtil;
    private final ObjectMapper objectMapper;

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) throws Exception {
        // CORS 预检请求直接放行
        if ("OPTIONS".equalsIgnoreCase(request.getMethod())) {
            return true;
        }
        String auth = request.getHeader("Authorization");
        if (auth == null || !auth.startsWith("Bearer ")) {
            return reject(request, response, 401, "未登录或 token 缺失");
        }

        Claims claims;
        try {
            claims = jwtUtil.parse(auth.substring(7));
        } catch (Exception e) {
            return reject(request, response, 401, "token 无效或已过期");
        }

        request.setAttribute(ATTR_USER_ID, Long.valueOf(claims.getSubject()));
        // 改造前签发的 token 里没有这枚 claim，取出来是 null（Caller 会当普通用户处理）
        String roleCode = claims.get("roleCode", String.class);
        request.setAttribute(ATTR_ROLE_CODE, roleCode);

        // 权限检查统一放这里，规则只有一份；注解标在方法上，加新接口不会漏
        if (handler instanceof HandlerMethod method
                && method.getMethodAnnotation(RequireAdmin.class) != null
                && !Caller.ROLE_ADMIN.equals(roleCode)) {
            return reject(request, response, 403, "需要管理员权限");
        }
        return true;
    }

    private boolean reject(HttpServletRequest request, HttpServletResponse response,
                           int code, String message) throws Exception {
        // 拒绝也要留痕：线上"点了没反应"多半是这里，访问日志只有状态码，原因记在这儿
        log.warn("拒绝 {} {} → {} {}", request.getMethod(), request.getRequestURI(), code, message);
        response.setStatus(code);
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.getWriter().write(objectMapper.writeValueAsString(Result.error(code, message)));
        return false;
    }
}
