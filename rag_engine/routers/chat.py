"""
RAG 聊天路由

提供两个端点：
- POST /chat        → 非流式，一次返回完整结果
- POST /chat/stream → 流式 SSE，逐步返回检索来源→回答→置信度
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from core.dependencies import get_rag_service, get_conversation_service
from models.chat import ChatRequest, ChatResponse
from services.rag_service import RAGService
from services.conversation_service import ConversationService

router = APIRouter()


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="RAG 问答（非流式）",
    description="发送问题，返回完整回答、来源引用和置信度。传入 conversation_id 可继续多轮对话。",
)
async def chat(
    request: ChatRequest,
    rag: RAGService = Depends(get_rag_service),
    conv: ConversationService = Depends(get_conversation_service),
) -> ChatResponse:
    result = await rag.chat(
        query=request.question,
        conversation_id=request.conversation_id,
        temperature=request.temperature,
        top_k=request.top_k,
    )
    # 更新对话摘要
    conv.upsert(
        conv_id=result.conversation_id,
        title=request.question[:80],
        message_count=1,  # 后续会改为从状态中计算
    )
    return result


@router.post(
    "/chat/stream",
    summary="RAG 问答（流式 SSE）",
    description="与 /chat 功能相同，但以 Server-Sent Events 格式逐步返回结果。"
                "事件类型：sources → answer → confidence → done。",
)
async def chat_stream(
    request: ChatRequest,
    rag: RAGService = Depends(get_rag_service),
    conv: ConversationService = Depends(get_conversation_service),
):
    """流式 RAG 问答，SSE 格式"""
    # 预先确定对话 ID，记录到侧边栏（调用方不传则新生成）
    cid = request.conversation_id or str(uuid.uuid4())
    conv.upsert(
        conv_id=cid,
        title=request.question[:80],  # 截取前80字符作为标题
        message_count=1,
    )

    # 启动流式生成（传入已有 cid，避免内部重复生成）
    stream = rag.chat_stream(
        query=request.question,
        conversation_id=cid,
        temperature=request.temperature,
        top_k=request.top_k,
    )
    # 返回 SSE（Server-Sent Events）流
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",        # 禁止浏览器缓存
            "Connection": "keep-alive",          # 保持长连接
            "X-Accel-Buffering": "no",           # 禁用 nginx 缓冲
        },
    )
