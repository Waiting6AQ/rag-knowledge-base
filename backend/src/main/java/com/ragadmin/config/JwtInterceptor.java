package com.ragadmin.config;

import com.ragadmin.common.Result;
import com.ragadmin.util.JwtUtil;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.jsonwebtoken.Claims;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import java.nio.charset.StandardCharsets;

/**
 * JWT 拦截器：校验 Authorization: Bearer <token>
 * 通过后把 userId / roleId 放入 request 属性，Controller 直接取
 */
@Component
@RequiredArgsConstructor
public class JwtInterceptor implements HandlerInterceptor {

    public static final String ATTR_USER_ID = "userId";
    public static final String ATTR_ROLE_ID = "roleId";

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
            return reject(response, 401, "未登录或 token 缺失");
        }
        try {
            Claims claims = jwtUtil.parse(auth.substring(7));
            request.setAttribute(ATTR_USER_ID, Long.valueOf(claims.getSubject()));
            request.setAttribute(ATTR_ROLE_ID, claims.get("roleId", Long.class));
            return true;
        } catch (Exception e) {
            return reject(response, 401, "token 无效或已过期");
        }
    }

    private boolean reject(HttpServletResponse response, int code, String message) throws Exception {
        response.setStatus(code);
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.getWriter().write(objectMapper.writeValueAsString(Result.error(code, message)));
        return false;
    }
}
