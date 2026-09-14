package com.ragadmin.service;

import com.ragadmin.mapper.ChatMessageMapper;
import com.ragadmin.mapper.ChatSessionMapper;
import com.ragadmin.model.ChatMessage;
import com.ragadmin.model.ChatSession;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

/**
 * ChatRecordService 单元测试：一轮问答的落库内容（含引用来源）与标题规则
 */
class ChatRecordServiceTest {

    private ChatSessionMapper sessionMapper;
    private ChatMessageMapper messageMapper;
    private ChatRecordService recordService;

    @BeforeEach
    void setUp() {
        sessionMapper = mock(ChatSessionMapper.class);
        messageMapper = mock(ChatMessageMapper.class);
        recordService = new ChatRecordService(sessionMapper, messageMapper);
    }

    private ChatSession session() {
        ChatSession s = new ChatSession();
        s.setId(1L);
        s.setTitle("新会话");
        return s;
    }

    @Test
    @DisplayName("落库内容：user 消息（无来源）+ assistant 消息（带引用来源 JSON）")
    void savesBothMessages() {
        String sourcesJson = "[{\"index\":1,\"source\":\"员工手册.docx\"}]";

        recordService.saveExchange(session(), "假期怎么规定", "根据员工手册，年假…", sourcesJson);

        ArgumentCaptor<ChatMessage> captor = ArgumentCaptor.forClass(ChatMessage.class);
        verify(messageMapper, times(2)).insert(captor.capture());
        List<ChatMessage> saved = captor.getAllValues();

        assertThat(saved.get(0).getRole()).isEqualTo("user");
        assertThat(saved.get(0).getContent()).isEqualTo("假期怎么规定");
        assertThat(saved.get(0).getSources()).isNull();
        assertThat(saved.get(0).getSessionId()).isEqualTo(1L);

        assertThat(saved.get(1).getRole()).isEqualTo("assistant");
        assertThat(saved.get(1).getContent()).isEqualTo("根据员工手册，年假…");
        assertThat(saved.get(1).getSources()).isEqualTo(sourcesJson);
    }

    @Test
    @DisplayName("标题规则：每轮更新为最新提问，超过 80 字截断")
    void titleFollowsLatestQuestionAndIsTruncated() {
        String longQuestion = "问".repeat(100);

        recordService.saveExchange(session(), longQuestion, "回答", null);

        verify(sessionMapper).updateTitle(eq(1L), argThat((String t) -> t.length() == 80));
    }

    @Test
    @DisplayName("标题规则：短提问原样作为标题")
    void titleKeepsShortQuestion() {
        recordService.saveExchange(session(), "你好", "您好", null);

        verify(sessionMapper).updateTitle(1L, "你好");
    }
}
