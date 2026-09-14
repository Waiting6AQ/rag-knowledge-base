package com.ragadmin.util;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.JwtException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * JwtUtil 单元测试：签发/解析回环、过期拒绝、伪造签名拒绝
 * 纯单元测试：直接 new，不启动 Spring 容器、不连数据库
 */
class JwtUtilTest {

    /** HS256 要求密钥 ≥ 256 bit（32 字节） */
    private static final String SECRET = "unit-test-secret-key-0123456789-abcdefghij";
    private static final String OTHER_SECRET = "another-secret-key-9876543210-zyxwvutsrq";

    private final JwtUtil jwtUtil = new JwtUtil(SECRET, 1);

    @Test
    @DisplayName("签发后解析回环：subject = userId，roleId 保留")
    void generateThenParse() {
        String token = jwtUtil.generate(42L, 2L);

        Claims claims = jwtUtil.parse(token);

        assertThat(claims.getSubject()).isEqualTo("42");
        assertThat(((Number) claims.get("roleId")).longValue()).isEqualTo(2L);
    }

    @Test
    @DisplayName("过期 token 被拒绝（expire-hours 取负数模拟已过期）")
    void expiredTokenIsRejected() {
        JwtUtil expired = new JwtUtil(SECRET, -1);
        String token = expired.generate(1L, 1L);

        assertThatThrownBy(() -> expired.parse(token))
                .isInstanceOf(ExpiredJwtException.class);
    }

    @Test
    @DisplayName("用其它密钥签发的 token（伪造）被拒绝")
    void tokenSignedWithAnotherKeyIsRejected() {
        String forged = new JwtUtil(OTHER_SECRET, 1).generate(1L, 1L);

        assertThatThrownBy(() -> jwtUtil.parse(forged))
                .isInstanceOf(JwtException.class);
    }
}
