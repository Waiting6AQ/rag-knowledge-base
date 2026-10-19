package com.ragadmin.controller;

import com.ragadmin.common.RequireAdmin;
import com.ragadmin.common.Result;
import com.ragadmin.config.JwtInterceptor;
import com.ragadmin.dto.UserInfo;
import com.ragadmin.service.UserService;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/** 用户管理：列表 / 删除，只对管理员开放 */
@RestController
@RequestMapping("/api/users")
@RequiredArgsConstructor
public class UserController {

    private final UserService userService;

    @RequireAdmin
    @GetMapping
    public Result<List<UserInfo>> list() {
        return Result.ok(userService.list());
    }

    @RequireAdmin
    @DeleteMapping("/{id}")
    public Result<Void> delete(HttpServletRequest request, @PathVariable Long id) {
        Long currentUserId = (Long) request.getAttribute(JwtInterceptor.ATTR_USER_ID);
        userService.delete(currentUserId, id);
        return Result.ok();
    }
}
