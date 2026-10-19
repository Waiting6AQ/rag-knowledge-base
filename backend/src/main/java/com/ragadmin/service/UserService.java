package com.ragadmin.service;

import com.ragadmin.common.BusinessException;
import com.ragadmin.dto.UserInfo;
import com.ragadmin.mapper.ChatMessageMapper;
import com.ragadmin.mapper.ChatSessionMapper;
import com.ragadmin.mapper.RoleMapper;
import com.ragadmin.mapper.UserMapper;
import com.ragadmin.model.ChatSession;
import com.ragadmin.model.Role;
import com.ragadmin.model.User;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestClient;

import java.util.List;

/**
 * 用户管理（管理员用）：列表、删除、注销自己
 *
 * 暂不支持改角色——目前只有一个内置管理员，改了也没人用；
 * 将来加的时候记得保留"不能改自己"的规则，避免把最后一个管理员降级后没人能进后台。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class UserService {

    private final UserMapper userMapper;
    private final RoleMapper roleMapper;
    private final ChatSessionMapper sessionMapper;
    private final ChatMessageMapper messageMapper;
    /** best-effort 清理专用客户端（3s/5s 超时），引擎挂起时不拖住删除操作 */
    @Qualifier("cleanupRestClient")
    private final RestClient cleanupRestClient;

    @Value("${app.ai-service-url}")
    private String aiServiceUrl;

    /** 列表（联 role 表带出角色码） */
    public List<UserInfo> list() {
        return userMapper.findAllWithRole();
    }

    /** 管理员删除其他用户：不能删自己，避免把自己锁在后台外 */
    @Transactional
    public void delete(Long currentUserId, Long targetUserId) {
        if (currentUserId.equals(targetUserId)) {
            throw BusinessException.badRequest("不能删除自己");
        }
        if (userMapper.findById(targetUserId) == null) {
            throw BusinessException.badRequest("用户不存在");
        }
        deleteCascade(targetUserId);
    }

    /**
     * 注销自己的账号（任何登录用户都能调）
     *
     * 管理员不允许注销：现在没有别的途径产生第二个管理员，管理员把自己删掉后
     * 就再没人能进后台。将来支持多管理员时，这里换成"最后一个管理员不能注销"的判断。
     */
    @Transactional
    public void deleteSelf(Long userId) {
        User user = userMapper.findById(userId);
        if (user == null) {
            throw BusinessException.badRequest("用户不存在");
        }
        Role adminRole = roleMapper.findByCode("ADMIN");
        if (adminRole != null && adminRole.getId().equals(user.getRoleId())) {
            throw BusinessException.badRequest("管理员账号不能注销");
        }
        deleteCascade(userId);
    }

    /** 级联删除：消息 → 会话（通知引擎） → 账号 */
    private void deleteCascade(Long targetUserId) {
        List<ChatSession> sessions = sessionMapper.findByUserId(targetUserId);
        for (ChatSession session : sessions) {
            messageMapper.deleteBySessionId(session.getId());
            sessionMapper.deleteById(session.getId());
            deleteEngineConversation(session.getConversationId());
        }
        userMapper.deleteById(targetUserId);
    }

    /** 通知引擎删对话：本地已删完，引擎失败只告警（与单条会话删除同一套策略） */
    private void deleteEngineConversation(String conversationId) {
        if (conversationId == null) {
            return;
        }
        try {
            cleanupRestClient.delete()
                    .uri(aiServiceUrl + "/api/v1/conversations/" + conversationId)
                    .retrieve()
                    .toBodilessEntity();
        } catch (Exception e) {
            log.warn("AI 服务对话清理失败（已忽略，本地删除不受影响）: {}", e.getMessage());
        }
    }
}
