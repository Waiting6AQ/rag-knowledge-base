package com.ragadmin.mapper;

import com.ragadmin.model.ChatMessage;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Select;

import java.util.List;

public interface ChatMessageMapper {

    @Select("SELECT * FROM chat_message WHERE session_id = #{sessionId} ORDER BY created_at ASC")
    List<ChatMessage> findBySessionId(Long sessionId);

    @Insert("INSERT INTO chat_message (session_id, role, content, sources) VALUES (#{sessionId}, #{role}, #{content}, #{sources})")
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insert(ChatMessage message);

    /** 删除会话时级联清理消息，防止孤儿数据 */
    @Delete("DELETE FROM chat_message WHERE session_id = #{sessionId}")
    int deleteBySessionId(Long sessionId);
}
