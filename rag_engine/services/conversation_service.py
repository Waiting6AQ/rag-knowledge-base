"""
对话元数据服务（PostgreSQL + SQLAlchemy ORM）

LangGraph 把对话完整状态存进 checkpoint 表（二进制），无法直接查询对话列表。
这个服务维护一张轻量的摘要表，专门用于"列出所有对话"这类快速查询。

与原 SQLite 实现的差异：
- 同步 sqlite3 → SQLAlchemy 异步会话（每个方法自开会话，用完即还）
- SELECT-then-INSERT/UPDATE → INSERT ... ON CONFLICT DO UPDATE（消除并发竞态）
- 时间戳 TEXT（裸 ISO）→ TIMESTAMPTZ，出参时转回 ISO 字符串（Pydantic 模型不变）
"""
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from models.conversation import (
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationSummary,
)
from models.tables import Conversation


def _iso(value: datetime) -> str:
    """TIMESTAMPTZ → ISO 字符串（Pydantic 模型的 created_at/updated_at 仍声明为 str）"""
    return value.isoformat()


class ConversationService:
    """管理对话摘要信息（ID、标题、消息数、时间）"""

    def __init__(self, session_factory: async_sessionmaker):
        self._session_factory = session_factory

    # ==================== CRUD ====================

    async def upsert(self, conv_id: str, title: str) -> None:
        """创建或更新对话摘要（单条语句，天然幂等，无竞态）"""
        stmt = (
            insert(Conversation)
            .values(id=conv_id, title=title)
            .on_conflict_do_update(
                index_elements=[Conversation.id],
                set_={
                    "title": title,
                    # 只刷新 updated_at，created_at 保持首次写入的值
                    "updated_at": func.now(),
                },
            )
        )
        async with self._session_factory() as session:
            await session.execute(stmt)
            await session.commit()

    async def list_conversations(
        self, limit: int = 50, offset: int = 0
    ) -> ConversationListResponse:
        """分页查询，按更新时间倒序"""
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(Conversation)
                    .order_by(Conversation.updated_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            total = await session.scalar(select(func.count()).select_from(Conversation)) or 0

        return ConversationListResponse(
            total=total,
            conversations=[
                ConversationSummary(
                    conversation_id=r.id,
                    title=r.title or "",
                    created_at=_iso(r.created_at),
                    updated_at=_iso(r.updated_at),
                )
                for r in rows
            ],
        )

    async def get_conversation(self, conv_id: str) -> ConversationDetailResponse | None:
        """获取对话详情（消息内容由路由层从 checkpoint 补齐）"""
        async with self._session_factory() as session:
            row = await session.get(Conversation, conv_id)

        if row is None:
            return None
        return ConversationDetailResponse(
            conversation_id=row.id,
            title=row.title or "",
            messages=[],
            created_at=_iso(row.created_at),
            updated_at=_iso(row.updated_at),
        )

    async def delete(self, conv_id: str) -> bool:
        """删除对话摘要，返回是否真的删掉了（供路由层判断 404）"""
        async with self._session_factory() as session:
            result = await session.execute(
                delete(Conversation).where(Conversation.id == conv_id)
            )
            await session.commit()
            return result.rowcount > 0
