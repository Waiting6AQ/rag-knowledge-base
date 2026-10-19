package com.ragadmin.mapper;

import com.ragadmin.dto.UserInfo;
import com.ragadmin.model.User;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/**
 * 用户表 Mapper
 * 简单查询用注解式；复杂 SQL（动态条件/联表）后续走 XML
 * #{} 预编译占位符，防 SQL 注入
 */
public interface UserMapper {

    @Select("SELECT * FROM user WHERE id = #{id}")
    User findById(Long id);

    @Select("SELECT * FROM user WHERE username = #{username}")
    User findByUsername(String username);

    /** 管理页列表：联 role 表带出角色码（map-underscore-to-camel-case 负责 role_code → roleCode） */
    @Select("""
            SELECT u.id, u.username, r.code AS role_code, u.created_at
            FROM user u JOIN role r ON r.id = u.role_id
            ORDER BY u.id
            """)
    List<UserInfo> findAllWithRole();

    @Delete("DELETE FROM user WHERE id = #{id}")
    int deleteById(Long id);

    @Update("UPDATE user SET password_hash = #{passwordHash} WHERE id = #{id}")
    int updatePassword(@Param("id") Long id, @Param("passwordHash") String passwordHash);

    @Insert("INSERT INTO user (username, password_hash, role_id) VALUES (#{username}, #{passwordHash}, #{roleId})")
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insert(User user);
}
