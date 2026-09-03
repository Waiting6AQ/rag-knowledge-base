"""
对话元数据服务

SqliteSaver 把对话完整状态存为二进制，无法直接查询对话列表。
这个服务维护一张轻量的摘要表，专门用于"列出所有对话"这类快速查询。
"""
import os
import sqlite3
from datetime import datetime
from models.conversation import (
    ConversationSummary,
    ConversationListResponse,
    ConversationDetailResponse,
    ConversationDeleteResponse,
    MessageDetail,
)


class ConversationService:
    """管理对话摘要信息（ID、标题、消息数、时间）"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        """创建新连接，线程安全"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """建表（表不存在才创建）"""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    message_count INTEGER DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            conn.commit()

    # ==================== CRUD ====================

    def upsert(self, conv_id: str, title: str, message_count: int):
        """创建或更新对话摘要"""
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            exists = conn.execute(
                "SELECT id FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()
            if exists:
                conn.execute(
                    "UPDATE conversations SET title=?, message_count=?, updated_at=? WHERE id=?",
                    (title, message_count, now, conv_id),
                )
            else:
                conn.execute(
                    "INSERT INTO conversations (id, title, message_count, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (conv_id, title, message_count, now, now),
                )
            conn.commit()

    def list_conversations(self, limit: int = 50, offset: int = 0) -> ConversationListResponse:
        """分页查询，按更新时间倒序"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]

        return ConversationListResponse(
            total=total,
            conversations=[
                ConversationSummary(
                    conversation_id=r["id"],
                    title=r["title"],
                    message_count=r["message_count"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ],
        )

    def get_conversation(self, conv_id: str) -> ConversationDetailResponse | None:
        """获取对话详情"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()
        if not row:
            return None
        # 消息详情需要从 checkpoints.db 读取，后续在路由层整合
        return ConversationDetailResponse(
            conversation_id=row["id"],
            title=row["title"],
            messages=[],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def delete(self, conv_id: str) -> bool:
        """删除对话摘要"""
        with self._get_conn() as conn:
            cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            conn.commit()
            return cur.rowcount > 0
