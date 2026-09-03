package com.ragadmin.service;

import com.ragadmin.common.BusinessException;
import com.ragadmin.dto.LoginRequest;
import com.ragadmin.dto.LoginResponse;
import com.ragadmin.dto.RegisterRequest;
import com.ragadmin.mapper.RoleMapper;
import com.ragadmin.mapper.UserMapper;
import com.ragadmin.model.Role;
import com.ragadmin.model.User;
import com.ragadmin.util.JwtUtil;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

@Slf4j
@Service
@RequiredArgsConstructor
public class AuthService {

    private final UserMapper userMapper;
    private final RoleMapper roleMapper;
    private final PasswordEncoder passwordEncoder;
    private final JwtUtil jwtUtil;

    /** 注册：默认 USER 角色，密码 BCrypt 哈希存储 */
    public User register(RegisterRequest req) {
        if (userMapper.findByUsername(req.getUsername()) != null) {
            throw BusinessException.badRequest("用户名已存在");
        }
        Role userRole = roleMapper.findByCode("USER");
        User user = new User();
        user.setUsername(req.getUsername());
        user.setPasswordHash(passwordEncoder.encode(req.getPassword()));
        user.setRoleId(userRole.getId());
        userMapper.insert(user);
        return user;
    }

    /** 登录：校验密码，签发 JWT */
    public LoginResponse login(LoginRequest req) {
        User user = userMapper.findByUsername(req.getUsername());
        if (user == null || !passwordEncoder.matches(req.getPassword(), user.getPasswordHash())) {
            throw BusinessException.badRequest("用户名或密码错误");
        }
        Role role = roleMapper.findById(user.getRoleId());
        String token = jwtUtil.generate(user.getId(), user.getRoleId());
        return new LoginResponse(token,
                new LoginResponse.UserInfo(user.getId(), user.getUsername(), role.getCode()));
    }

    public User getById(Long id) {
        return userMapper.findById(id);
    }

    /** 启动时预置管理员：admin / admin123（仅首次创建） */
    @PostConstruct
    public void ensureAdmin() {
        if (userMapper.findByUsername("admin") == null) {
            Role adminRole = roleMapper.findByCode("ADMIN");
            User admin = new User();
            admin.setUsername("admin");
            admin.setPasswordHash(passwordEncoder.encode("admin123"));
            admin.setRoleId(adminRole.getId());
            userMapper.insert(admin);
            log.info("已创建默认管理员账号 admin（密码 admin123，请尽快修改）");
        }
    }
}
