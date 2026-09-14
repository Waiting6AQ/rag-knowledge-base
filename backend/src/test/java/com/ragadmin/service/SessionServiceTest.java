package com.ragadmin.service;

import com.ragadmin.common.BusinessException;
import com.ragadmin.mapper.ChatMessageMapper;
import com.ragadmin.mapper.ChatSessionMapper;
import com.ragadmin.model.ChatSession;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowableOfType;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * SessionService 单元测试：会话归属校验（防水平越权）、创建、删除级联与降级
 * 用 Mockito 隔离 Mapper 与 HTTP 客户端；不启动 Spring、不连库
 */
class SessionServiceTest {

    private ChatSessionMapper sessionMapper;
    private ChatMessageMapper messageMapper;
    private SessionService sessionService;

    @BeforeEach
    void setUp() {
        sessionMapper = mock(ChatSessionMapper.class);
        messageMapper = mock(ChatMessageMapper.class);
        sessionService = new SessionService(sessionMapper, messageMapper, mock(RestClient.class));
        ReflectionTestUtils.setField(sessionService, "aiServiceUrl", "http://localhost:8000");
    }

    private ChatSession sessionOf(Long id, Long userId) {
        ChatSession s = new ChatSession();
        s.setId(id);
        s.setUserId(userId);
        s.setConversationId("conv-" + id);
        s.setTitle("新会话");
        return s;
    }

    @Test
    @DisplayName("会话不存在：抛 400")
    void notFound() {
        when(sessionMapper.findById(1L)).thenReturn(null);

        BusinessException ex = catchThrowableOfType(
                BusinessException.class, () -> sessionService.getOwnedSession(1L, 1L));

        assertThat(ex).isNotNull();
        assertThat(ex.getCode()).isEqualTo(400);
        assertThat(ex.getMessage()).contains("会话不存在");
    }

    @Test
    @DisplayName("访问他人会话：抛 403（防水平越权）")
    void forbiddenForAnotherUsersSession() {
        when(sessionMapper.findById(1L)).thenReturn(sessionOf(1L, 999L));

        BusinessException ex = catchThrowableOfType(
                BusinessException.class, () -> sessionService.getOwnedSession(1L, 1L));

        assertThat(ex).isNotNull();
        assertThat(ex.getCode()).isEqualTo(403);
    }

    @Test
    @DisplayName("本人会话：正常返回")
    void returnsOwnedSession() {
        ChatSession session = sessionOf(1L, 7L);
        when(sessionMapper.findById(1L)).thenReturn(session);

        // 注意参数顺序：getOwnedSession(userId, sessionId)
        assertThat(sessionService.getOwnedSession(7L, 1L)).isSameAs(session);
    }

    @Test
    @DisplayName("创建会话：生成 conversationId 与默认标题")
    void createGeneratesConversationId() {
        sessionService.create(7L);

        ArgumentCaptor<ChatSession> captor = ArgumentCaptor.forClass(ChatSession.class);
        verify(sessionMapper).insert(captor.capture());
        ChatSession inserted = captor.getValue();

        assertThat(inserted.getUserId()).isEqualTo(7L);
        assertThat(inserted.getTitle()).isEqualTo("新会话");
        assertThat(inserted.getConversationId()).isNotBlank();
    }

    @Test
    @DisplayName("删除会话：级联删除消息与会话；引擎清理失败不抛出（best-effort 降级）")
    void deleteCascadesAndDegradesWhenEngineUnreachable() {
        when(sessionMapper.findById(1L)).thenReturn(sessionOf(1L, 7L));

        // 引擎不可达：清理专用客户端直接抛异常
        RestClient failingClient = mock(RestClient.class);
        when(failingClient.delete()).thenThrow(new RuntimeException("AI 服务不可达"));
        SessionService svc = new SessionService(sessionMapper, messageMapper, failingClient);
        ReflectionTestUtils.setField(svc, "aiServiceUrl", "http://localhost:8000");

        svc.delete(7L, 1L);   // 不应抛异常

        verify(messageMapper).deleteBySessionId(1L);
        verify(sessionMapper).deleteById(1L);
    }
}
