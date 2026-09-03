package com.ragadmin.controller;

import com.ragadmin.common.Result;
import com.ragadmin.config.JwtInterceptor;
import com.ragadmin.dto.LoginRequest;
import com.ragadmin.dto.LoginResponse;
import com.ragadmin.dto.RegisterRequest;
import com.ragadmin.model.User;
import com.ragadmin.service.AuthService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService authService;

    @PostMapping("/register")
    public Result<User> register(@Valid @RequestBody RegisterRequest req) {
        return Result.ok(authService.register(req));
    }

    @PostMapping("/login")
    public Result<LoginResponse> login(@Valid @RequestBody LoginRequest req) {
        return Result.ok(authService.login(req));
    }

    /** 当前登录用户信息（测试拦截器用） */
    @GetMapping("/me")
    public Result<User> me(HttpServletRequest request) {
        Long userId = (Long) request.getAttribute(JwtInterceptor.ATTR_USER_ID);
        return Result.ok(authService.getById(userId));
    }
}
