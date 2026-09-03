-- ============================================================
-- RAG 知识库问答系统 - 建表脚本
-- 由 Spring Boot sql.init 在启动时执行（IF NOT EXISTS，幂等）
-- ============================================================

-- 角色表（简化 RBAC：角色级控制）
CREATE TABLE IF NOT EXISTS `role` (
  `id`         BIGINT AUTO_INCREMENT PRIMARY KEY,
  `code`       VARCHAR(32) NOT NULL UNIQUE COMMENT '角色编码：USER / ADMIN',
  `name`       VARCHAR(64) NOT NULL COMMENT '角色名称',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) COMMENT='角色表';

-- 用户表（统一账号体系，通过 role_id 关联角色）
CREATE TABLE IF NOT EXISTS `user` (
  `id`            BIGINT AUTO_INCREMENT PRIMARY KEY,
  `username`      VARCHAR(64)  NOT NULL UNIQUE COMMENT '登录名',
  `password_hash` VARCHAR(100) NOT NULL COMMENT 'BCrypt 哈希，不存明文',
  `role_id`       BIGINT       NOT NULL COMMENT '角色ID',
  `created_at`    DATETIME DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT `fk_user_role` FOREIGN KEY (`role_id`) REFERENCES `role`(`id`)
) COMMENT='用户表';

-- 会话表（业务侧自持记录：user_id ↔ conversation_id 归属映射）
CREATE TABLE IF NOT EXISTS `chat_session` (
  `id`              BIGINT AUTO_INCREMENT PRIMARY KEY,
  `user_id`         BIGINT       NOT NULL COMMENT '所属用户',
  `conversation_id` VARCHAR(64)  NOT NULL COMMENT 'AI 服务侧会话ID（LangGraph checkpoint）',
  `title`           VARCHAR(128) DEFAULT '新会话' COMMENT '会话标题（取首条消息截断）',
  `created_at`      DATETIME DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY `idx_session_user` (`user_id`)
) COMMENT='会话表';

-- 消息表（会话的每一条问答记录，业务侧审计用）
-- intent：AI 回复的意图标签（tech_support/order_service/product_consult/chitchat/web_search/escalate），仅 assistant 消息有值
-- 注：Python 侧 checkpoint 的 intent 是每轮状态（会被覆盖），历史意图只能由业务侧自存
CREATE TABLE IF NOT EXISTS `chat_message` (
  `id`         BIGINT AUTO_INCREMENT PRIMARY KEY,
  `session_id` BIGINT       NOT NULL COMMENT '所属会话',
  `role`       VARCHAR(16)  NOT NULL COMMENT 'user / assistant',
  `content`    TEXT         NOT NULL COMMENT '消息内容',
  `sources`    TEXT         DEFAULT NULL COMMENT '引用来源 JSON（assistant 消息，历史会话展示用）',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY `idx_message_session` (`session_id`)
) COMMENT='消息表';

-- 种子角色（固定 id：1=USER，2=ADMIN）
INSERT IGNORE INTO `role` (`id`, `code`, `name`) VALUES
  (1, 'USER',  '普通用户'),
  (2, 'ADMIN', '管理员');
