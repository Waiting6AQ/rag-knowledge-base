"""
对话管理相关 Pydantic 模型

用于对话列表、详情查看、删除等管理接口
"""
from pydantic import BaseModel


# ---------- 列表 ----------
class ConversationSummary(BaseModel):
    """对话列表中的摘要信息（不包含完整消息内容，节省带宽）"""
    conversation_id: str                         # 对话唯一 ID
    title: str                                   # 对话标题（取第一条用户消息的前 80 字）
    message_count: int                           # 对话中的消息总数
    created_at: str                              # 创建时间（ISO 格式）
    updated_at: str                              # 最后更新时间


class ConversationListResponse(BaseModel):
    """对话列表响应"""
    total: int                                   # 对话总数
    conversations: list[ConversationSummary]     # 对话摘要列表


# ---------- 详情 ----------
class MessageDetail(BaseModel):
    """单条消息"""
    role: str                                    # "user" 或 "assistant"
    content: str                                 # 消息内容
    sources: list = []                           # 来源文档列表（仅 assistant 消息有）
    timestamp: str | None = None                 # 消息时间戳（可能为空）


class ConversationDetailResponse(BaseModel):
    """对话详情（含完整消息历史）"""
    conversation_id: str
    title: str
    messages: list[MessageDetail]                # 完整消息列表
    created_at: str
    updated_at: str


# ---------- 删除 ----------
class ConversationDeleteResponse(BaseModel):
    """删除对话的响应"""
    conversation_id: str
    status: str = "deleted"
