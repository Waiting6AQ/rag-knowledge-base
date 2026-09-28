"""
SQLAlchemy ORM 模型（业务表）

注意：LangGraph 的 checkpoint 表不在这里。它由 AsyncPostgresSaver 自己创建
（checkpoints / checkpoint_blobs / checkpoint_writes / checkpoint_migrations），
结构和迁移都由框架管理，不参与 ORM 映射。
"""
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""


class Conversation(Base):
    """对话摘要（列表页用；完整消息在 LangGraph checkpoint 里）"""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # TIMESTAMPTZ 而非 TEXT：
    # ① 旧实现存裸 ISO 字符串（无时区），跨时区会静默错序，且 JS 的 new Date() 会当本地时间解析
    # ② server_default=NOW() 让时间由数据库生成，不依赖应用容器的时区设置
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # 列表页按 updated_at 倒序。单列排序不需要 DESC 索引——
    # PostgreSQL 的 btree 索引可以反向扫描，两种写法执行计划相同
    __table_args__ = (Index("conversations_updated_at_idx", "updated_at"),)
