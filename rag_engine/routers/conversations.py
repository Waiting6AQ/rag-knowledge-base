"""
对话管理路由

提供对话列表、详情查看、删除功能。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from core.dependencies import get_conversation_service, get_rag_service
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
    rag: RAGService = Depends(get_rag_service),
) -> ConversationDeleteResponse:
    # 顺序：先删 checkpoint，再删元数据。
    # 反过来的话，删 checkpoint 失败时元数据已消失，那条 checkpoint 就成了
    # 用户看不到、也再没有入口能删掉的孤儿数据
    await rag.delete_history(conversation_id)
    if not await service.delete(conversation_id):
        raise HTTPException(status_code=404, detail="对话不存在")
    return ConversationDeleteResponse(conversation_id=conversation_id)
