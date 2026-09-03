-- ============================================================
-- 数据库初始化（可选）
-- 应用默认自动建库：JDBC URL 带 createDatabaseIfNotExist=true，
-- 且服务器默认字符集为 utf8mb4（中文正常），一般无需手动执行本文件。
-- 本文件仅在需要手动控制建库（如自定义字符集/排序规则）时使用。
-- ============================================================

-- 不指定 COLLATE：跟随 MySQL 版本默认（8.0 为 utf8mb4_0900_ai_ci）
CREATE DATABASE IF NOT EXISTS `agent_admin`
  DEFAULT CHARACTER SET utf8mb4;
