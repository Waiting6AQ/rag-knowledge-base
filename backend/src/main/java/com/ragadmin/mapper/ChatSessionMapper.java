package com.ragadmin.mapper;

import com.ragadmin.model.ChatSession;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/**
 * 会话表 Mapper
 * 简单查询用注解；分页 + 关键词搜索走 XML（见 ChatSessionMapper.xml）
 */
public interface ChatSessionMapper {

    @Select("SELECT * FROM chat_session WHERE id = #{id}")
    ChatSession findById(Long id);

    @Insert("INSERT INTO chat_session (user_id, conversation_id, title) VALUES (#{userId}, #{conversationId}, #{title})")
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insert(ChatSession session);

    @Delete("DELETE FROM chat_session WHERE id = #{id}")
    int deleteById(Long id);

    /** 标题更新（对齐 Python 侧：发消息时更新为消息前 80 字） */
    @Update("UPDATE chat_session SET title = #{title} WHERE id = #{id}")
    int updateTitle(@Param("id") Long id, @Param("title") String title);

    /** 分页查询（XML：复杂 SQL 走 XML 的示范） */
    List<ChatSession> selectPage(@Param("userId") Long userId,
                                 @Param("offset") int offset,
                                 @Param("size") int size);

    /** 统计总数（XML：与 selectPage 相同条件） */
    long countByUser(@Param("userId") Long userId);
}
