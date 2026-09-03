package com.ragadmin.mapper;

import com.ragadmin.model.User;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Select;

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

    @Insert("INSERT INTO user (username, password_hash, role_id) VALUES (#{username}, #{passwordHash}, #{roleId})")
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insert(User user);
}
