package com.ragadmin.service;

import com.ragadmin.common.BusinessException;
import com.ragadmin.dto.AiChatResponse;
import com.ragadmin.dto.ChatRequest;
import com.ragadmin.dto.ChatResponse;
import com.ragadmin.mapper.ChatMessageMapper;
import com.ragadmin.mapper.ChatSessionMapper;
import com.ragadmin.model.ChatMessage;
import com.ragadmin.model.ChatSession;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Map;

/**
 * 聊天服务：Java 网关转发 rag_engine（AI 服务）+ 业务侧自持记录
 *
 * 链路：校验/建会话 → 转发 AI（带 X-User-Id）→ 落库（user + assistant 消息）→ 标题更新
 * 降级：AI 服务不可达/超时 → SSE error 事件 + 友好提示，不落库
 *
 * 流式采用【原样透传】：Python 的 SSE 字节流逐行搬给前端（格式 100% 保留），
 * 只劫持 done 事件（附加 session_id）。StreamingResponseBody 由 Spring 自动异步调用（请求线程释放）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ChatService {

    private static final String DEFAULT_TITLE = "新会话";

    private final SessionService sessionService;
    private final ChatSessionMapper sessionMapper;
    private final ChatMessageMapper messageMapper;
    private final RestClient restClient;
    private final ObjectMapper objectMapper;

    @Value("${app.ai-service-url}")
    private String aiServiceUrl;

    public ChatResponse chat(Long userId, ChatRequest req) {
        // 1. 定位会话：带了 session_id 校验归属，没带自动创建
        ChatSession session = resolveSession(userId, req);

        // 2. 转发 AI 服务（超时/降级在方法内处理）
        AiChatResponse ai = callAiService(userId, session, req.getQuestion());

        // 3. 落库：用户消息 + AI 回答（带引用来源 JSON）
        saveMessage(session.getId(), "user", req.getQuestion(), null);
        saveMessage(session.getId(), "assistant", ai.getAnswer(), sourcesToJson(ai.getSources()));

        // 4. 标题更新：对齐 Python 侧 message[:80]，仅首次
        if (DEFAULT_TITLE.equals(session.getTitle())) {
            sessionMapper.updateTitle(session.getId(), truncate(req.getQuestion()));
        }

        return new ChatResponse(
                session.getId(),
                ai.getAnswer(),
                ai.getSources(),
                ai.getConfidence() != null ? ai.getConfidence() : 0.0,
                Boolean.TRUE.equals(ai.getRagUsed())
        );
    }

    /** 会话解析：带会话ID（数据库主键）必须属于当前用户；否则新建 */
    private ChatSession resolveSession(Long userId, ChatRequest req) {
        if (req.getSessionId() != null) {
            return sessionService.getOwnedSession(userId, req.getSessionId());
        }
        return sessionService.create(userId);
    }

    /** 非流式转发 AI：POST {ai-url}/api/v1/chat，注入 X-User-Id 可信头（预留数据隔离/审计） */
    private AiChatResponse callAiService(Long userId, ChatSession session, String question) {
        try {
            return restClient.post()
                    .uri(aiServiceUrl + "/api/v1/chat")
                    .header("X-User-Id", String.valueOf(userId))
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of(
                            "question", question,
                            "conversation_id", session.getConversationId()))
                    .retrieve()
                    .body(AiChatResponse.class);
        } catch (ResourceAccessException e) {
            log.warn("AI 服务不可达或超时: {}", e.getMessage());
            throw new BusinessException(503, "AI 服务暂时不可用，请稍后再试");
        } catch (Exception e) {
            log.error("调用 AI 服务失败", e);
            throw new BusinessException(503, "AI 服务暂时不可用，请稍后再试");
        }
    }

    /**
     * 流式聊天：原样透传 rag_engine 的 SSE 流（打字机效果）
     * StreamingResponseBody：Spring 自动在异步线程调用 writeTo，请求线程立即释放
     */
    public StreamingResponseBody chatStream(Long userId, ChatRequest req) {
        ChatSession session = resolveSession(userId, req);
        return outputStream -> relayStream(outputStream, userId, session, req.getQuestion());
    }

    /**
     * 行级原样透传（具体分支逻辑见 relayLines）：Python 的 SSE 格式 100% 保留给前端，
     * 转发期间旁路记录落库所需元数据（token 拼接完整回复、sources 引用来源），不干扰转发
     */
    private void relayStream(OutputStream outputStream, Long userId, ChatSession session, String userMsg) {
        StringBuilder fullReply = new StringBuilder();
        String sources = null;
        try {
            String json = objectMapper.writeValueAsString(Map.of(
                    "question", userMsg,
                    "conversation_id", session.getConversationId()));
            // exchange 的回调返回值即 exchange 的返回值——sources 在方法内赋值，无 lambda 闭包问题
            sources = restClient.post()
                    .uri(aiServiceUrl + "/api/v1/chat/stream")
                    .header("X-User-Id", String.valueOf(userId))
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(json)
                    .exchange((request, response) -> {
                        if (!response.getStatusCode().is2xxSuccessful()) {
                            throw new RuntimeException("AI 服务返回 HTTP " + response.getStatusCode().value());
                        }
                        return relayLines(outputStream, response.getBody(), session, fullReply);
                    });
        } catch (Exception e) {
            log.error("SSE 透传失败", e);
            writeError(outputStream);
            return;
        }
        // 流正常结束：落库（user + assistant 消息 + 引用来源 + 标题更新）
        persistExchange(session, userMsg, fullReply.toString(), sources);
    }

    /**
     * 逐行透传，返回旁路记录的 sources（引用来源 JSON，sources 事件在回答前必到，早于 done 更可靠）
     * - event 行：记录 pendingEvent（当前事件名），原样写
     * - data 行：pendingEvent == sources → 旁路记录 sources（落库用），仍原样转发（前端也要显示）
     *            pendingEvent == done → 劫持（解析 + 加 session_id + 重写）
     *            pendingEvent == null → 裸 data = token → 原样写 + 旁路拼 fullReply
     *            其他（progress）→ 原样写
     * - 空行：事件结束，重置 pendingEvent
     */
    private String relayLines(OutputStream outputStream, InputStream in, ChatSession session, StringBuilder fullReply) {
        String pendingEvent = null;   // 当前正在组装的事件名（event 行已到、data 行待配对）
        String sources = null;
        try {
            BufferedReader reader = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8));
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isEmpty()) {
                    outputStream.write("\n".getBytes(StandardCharsets.UTF_8));   // 事件分隔
                    pendingEvent = null;                                          // 事件结束
                } else if (line.startsWith("event:")) {
                    pendingEvent = line.substring(6).trim();
                    writeLine(outputStream, line);
                } else if (line.startsWith("data:")) {
                    String data = line.substring(5).trim();
                    if ("sources".equals(pendingEvent)) {
                        // sources 事件（回答前必到）：旁路记录原始 JSON（落库用）——不等 done，
                        // 长流程可能被超时掐断，但引用来源此时已可得；仍原样转发给前端显示
                        sources = data;
                        writeLine(outputStream, line);
                    } else if ("done".equals(pendingEvent)) {
                        // 劫持 done：附加 session_id（前端继续对话用）
                        @SuppressWarnings("unchecked")
                        Map<String, Object> done = objectMapper.readValue(data, Map.class);
                        done.put("session_id", session.getId());
                        writeLine(outputStream, "data: " + objectMapper.writeValueAsString(done));
                    } else if (pendingEvent == null) {
                        // 裸 data = token 事件：原样写，同时旁路拼一份完整回复（落库用）
                        @SuppressWarnings("unchecked")
                        Map<String, Object> tokenData = objectMapper.readValue(data, Map.class);
                        fullReply.append(String.valueOf(tokenData.getOrDefault("token", "")));
                        writeLine(outputStream, line);
                    } else {
                        writeLine(outputStream, line);
                    }
                } else {
                    writeLine(outputStream, line);
                }
                outputStream.flush();   // 每行 flush 保证实时到达（打字机效果）
            }
        } catch (Exception e) {
            log.error("SSE 流读取/转发失败", e);
        }
        return sources;
    }

    private void writeLine(OutputStream outputStream, String line) throws Exception {
        outputStream.write((line + "\n").getBytes(StandardCharsets.UTF_8));
    }

    /** AI 服务不可达：向客户端发 error 事件（前端显示友好提示） */
    private void writeError(OutputStream outputStream) {
        try {
            writeLine(outputStream, "event: error");
            writeLine(outputStream, "data: AI 服务暂时不可用，请稍后再试");
            outputStream.write("\n".getBytes(StandardCharsets.UTF_8));
            outputStream.flush();
        } catch (Exception ignored) {
            // 客户端可能已断开
        }
    }

    /** 落库：用户消息 + AI 完整回复（带引用来源 JSON）+ 标题更新 */
    private void persistExchange(ChatSession session, String userMsg, String reply, String sources) {
        saveMessage(session.getId(), "user", userMsg, null);
        saveMessage(session.getId(), "assistant", reply, sources);
        if (DEFAULT_TITLE.equals(session.getTitle())) {
            sessionMapper.updateTitle(session.getId(), truncate(userMsg));
        }
    }

    private void saveMessage(Long sessionId, String role, String content, String sources) {
        ChatMessage msg = new ChatMessage();
        msg.setSessionId(sessionId);
        msg.setRole(role);
        msg.setContent(content);
        msg.setSources(sources);
        messageMapper.insert(msg);
    }

    /** 非流式响应的 sources 列表 → JSON 文本（落库格式，与流式旁路记录一致） */
    private String sourcesToJson(java.util.List<AiChatResponse.SourceInfo> sources) {
        if (sources == null || sources.isEmpty()) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(sources);
        } catch (Exception e) {
            log.error("sources 序列化失败", e);
            return null;
        }
    }

    private String truncate(String s) {
        return s.length() > 80 ? s.substring(0, 80) : s;
    }
}
