"""
对话管理路由

提供对话列表、详情查看、删除功能。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from core.dependencies import get_checkpointer, get_conversation_service, get_rag_service
from models.conversation import (
    ConversationListResponse,
    ConversationDetailResponse,
    ConversationDeleteResponse,
    MessageDetail,
)
from services.conversation_service import ConversationService
from services.rag_service import RAGService

router = APIRouter()


@router.get(
    "/",
    response_model=ConversationListResponse,
    summary="列出所有对话",
)
async def list_conversations(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationListResponse:
    return await service.list_conversations(limit=limit, offset=offset)


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetailResponse,
    summary="查看对话详情",
)
async def get_conversation(
    conversation_id: str,
    conv: ConversationService = Depends(get_conversation_service),
    rag: RAGService = Depends(get_rag_service),
) -> ConversationDetailResponse:
    detail = await conv.get_conversation(conversation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="对话不存在")

    # 从 checkpoints 读取真实消息
    history = await rag.get_history(conversation_id)
    messages = [
        MessageDetail(
            role=m["role"],
            content=m["content"],
            sources=m.get("sources", []),
            timestamp=None,  # checkpoints 不存储每条消息的时间
        )
        for m in history
    ]

    return ConversationDetailResponse(
        conversation_id=detail.conversation_id,
        title=detail.title,
        messages=messages,
        created_at=detail.created_at,
        updated_at=detail.updated_at,
    )


@router.delete(
    "/{conversation_id}",
    response_model=ConversationDeleteResponse,
    summary="删除对话",
)
async def delete_conversation(
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
    checkpointer: AsyncPostgresSaver = Depends(get_checkpointer),
) -> ConversationDeleteResponse:
    # 这里只依赖 checkpointer，不依赖 RAGService——删一个对话不需要构建整条 RAG 管线
    #
    # 用官方 adelete_thread 而非裸 SQL，原因有三：
    # - PG 版 saver.conn 是连接池对象，没有 .execute()
    # - PG 版表名是 checkpoint_blobs / checkpoint_writes（SQLite 叫 writes），
    #   blob 还单独拆了一张表——照抄旧 SQL 既会报错、也删不干净
    # - 它一次清三张表，且与 saver 内部锁的并发写是安全的
    #
    # 顺序：先删 checkpoint，再删元数据。
    # 反过来的话，删 checkpoint 失败时元数据已消失，那条 checkpoint 就成了
    # 用户看不到、也再没有入口能删掉的孤儿数据
    await checkpointer.adelete_thread(conversation_id)
    if not await service.delete(conversation_id):
        raise HTTPException(status_code=404, detail="对话不存在")
    return ConversationDeleteResponse(conversation_id=conversation_id)
