"""
聊天 / RAG 问答相关 Pydantic 模型

请求模型：定义客户端必须/可选传哪些字段，以及字段的约束（长度、范围）
响应模型：定义服务端返回的数据结构，用于生成 OpenAPI 文档
"""
from pydantic import BaseModel, Field


# ---------- 请求 ----------
class ChatRequest(BaseModel):
    """RAG 问答请求体"""
    question: str = Field(
        ...,                                      # ... 表示必填字段
        min_length=1,                             # 至少 1 个字符
        description="用户问题",
    )
    conversation_id: str | None = Field(
        None,                                     # 默认 None，不传则系统自动创建新对话
        description="对话ID，不传则新建对话",
    )
    temperature: float = Field(
        0.1,                                      # 默认值 0.1，让回答更确定
        ge=0,                                     # 大于等于 0
        le=1,                                     # 小于等于 1
        description="LLM 温度，控制回答的随机性",
    )
    top_k: int = Field(
        5,                                        # 默认返回 5 个最相关文档
        ge=1,
        le=20,
        description="检索返回的文档数量",
    )


# ---------- 响应 ----------
class SourceInfo(BaseModel):
    """检索到的来源文档信息"""
    index: int                                   # 来源编号（1, 2, 3...）
    source: str                                  # 来源文件名
    content_preview: str                         # 来源内容的前 100 字预览


class ChatResponse(BaseModel):
    """RAG 问答完整响应"""
    conversation_id: str                         # 对话 ID（用于多轮对话）
    answer: str                                  # LLM 生成的回答
    sources: list[SourceInfo]                    # 引用来源列表
    confidence: float = Field(..., ge=0, le=1)  # 置信度分数 0~1
    rewritten_query: str | None = None           # 多轮对话时改写后的查询（单轮为 None）
    rag_used: bool = False                       # 是否实际使用了 RAG（检索到了文档）
