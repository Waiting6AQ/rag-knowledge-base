"""
RAG 聊天路由

提供两个端点：
- POST /chat        → 非流式，一次返回完整结果
- POST /chat/stream → 流式 SSE，逐步返回检索来源→回答→置信度
"""
import logging
import time
import uuid
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from core.concurrency import AsyncConcurrencyLimiter
from core.dependencies import (
    get_rag_service,
    get_conversation_service,
    get_chat_limiter,
)
from models.chat import ChatRequest, ChatResponse
from services.rag_service import RAGService
from services.conversation_service import ConversationService

router = APIRouter()
logger = logging.getLogger(__name__)


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
    limiter: AsyncConcurrencyLimiter = Depends(get_chat_limiter),
) -> ChatResponse:
    started = time.perf_counter()
    # 并发闸门：整个问答算一个在途请求，排队超时抛 429
    try:
        async with limiter:
            result = await rag.chat(
                query=request.question,
                conversation_id=request.conversation_id,
                temperature=request.temperature,
                top_k=request.top_k,
            )
            # 更新对话摘要（写入 PG）
            await conv.upsert(
                conv_id=result.conversation_id,
                title=request.question[:80],
            )
    except BaseException as e:
        logger.warning("chat 失败 耗时=%.2fs: %s",
                       time.perf_counter() - started, type(e).__name__)
        raise
    logger.info("chat 完成 cid=%s 耗时=%.2fs",
                result.conversation_id, time.perf_counter() - started)
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
    limiter: AsyncConcurrencyLimiter = Depends(get_chat_limiter),
):
    """流式 RAG 问答，SSE 格式"""
    started = time.perf_counter()
    # 许可必须在构造 StreamingResponse 之前拿：拿不到时还能正常返回 429 JSON；
    # 等流开始之后再拒绝，HTTP 状态码已经发出去了，前端只会看到半截流。
    await limiter.acquire()
    try:
        # 预先确定对话 ID，记录到侧边栏（调用方不传则新生成）
        cid = request.conversation_id or str(uuid.uuid4())
        await conv.upsert(
            conv_id=cid,
            title=request.question[:80],  # 截取前80字符作为标题
        )

        # 启动流式生成（传入已有 cid，避免内部重复生成）
        stream = rag.chat_stream(
            query=request.question,
            conversation_id=cid,
            temperature=request.temperature,
            top_k=request.top_k,
        )

        async def guarded_stream():
            """流式生成器：无论正常结束、报错还是客户端断开，都归还许可"""
            ok = False
            try:
                async for chunk in stream:
                    yield chunk
                ok = True
            except BaseException as e:
                logger.warning("chat_stream 中断 cid=%s 耗时=%.2fs: %s",
                               cid, time.perf_counter() - started, type(e).__name__)
                raise
            finally:
                limiter.release()
                if ok:
                    logger.info("chat_stream 完成 cid=%s 耗时=%.2fs",
                                cid, time.perf_counter() - started)

        # 返回 SSE（Server-Sent Events）流
        return StreamingResponse(
            guarded_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",        # 禁止浏览器缓存
                "Connection": "keep-alive",          # 保持长连接
                "X-Accel-Buffering": "no",           # 禁用 nginx 缓冲
            },
        )
    except BaseException:
        # 拿到许可后、流启动前就失败（建会话 / 构造生成器抛错）：立刻归还再抛
        limiter.release()
        raise
