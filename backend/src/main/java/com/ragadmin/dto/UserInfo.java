package com.ragadmin.dto;

import lombok.Data;

import java.time.LocalDateTime;

/** 用户管理列表项（联 role 表带出角色码） */
@Data
public class UserInfo {

    private Long id;
    private String username;
    private String roleCode;
    private LocalDateTime createdAt;
}
