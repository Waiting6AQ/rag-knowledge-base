package com.ragadmin.model;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class User {
    private Long id;
    private String username;
    private String passwordHash;
    private Long roleId;
    private LocalDateTime createdAt;
}
