package com.ragadmin.mapper;

import com.ragadmin.model.Role;
import org.apache.ibatis.annotations.Select;

public interface RoleMapper {

    @Select("SELECT * FROM role WHERE id = #{id}")
    Role findById(Long id);

    @Select("SELECT * FROM role WHERE code = #{code}")
    Role findByCode(String code);
}
