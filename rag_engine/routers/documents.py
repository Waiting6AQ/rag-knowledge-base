"""
文档管理路由

提供文档的上传、列表、删除功能。
上传的文档经分块→嵌入后写入向量库，元数据登记在 PostgreSQL。
"""
from fastapi import APIRouter, File, UploadFile, Depends
from fastapi.responses import FileResponse
from core.caller import Caller, get_caller
from core.dependencies import get_document_service
from models.document import (
    DocumentUploadResponse,
    DocumentListResponse,
    DocumentDeleteResponse,
    DocumentContentResponse,
)
from services.document_service import DocumentService

router = APIRouter()


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=201,
    summary="上传文档并索引",
    description="上传 .txt / .pdf / .md 文件，自动分块、生成向量、存入向量库。",
)
async def upload(
    file: UploadFile = File(...),
    caller: Caller = Depends(get_caller),
    service: DocumentService = Depends(get_document_service),
) -> DocumentUploadResponse:
    return await service.upload(file, caller)


@router.get(
    "/",
    response_model=DocumentListResponse,
    summary="列出所有文档",
    description="返回知识库中所有已索引文档的摘要信息。",
)
async def list_documents(
    service: DocumentService = Depends(get_document_service),
) -> DocumentListResponse:
    # 元数据在 PG：异步查询会话直接 await，不再需要丢线程池
    return await service.list_documents()


@router.get(
    "/{doc_id}/content",
    response_model=DocumentContentResponse,
    summary="读取文档全文",
    description="用索引时的同一套解析器读取原始文件，返回正文供前端点开查看。",
)
async def get_content(
    doc_id: str,
    service: DocumentService = Depends(get_document_service),
) -> DocumentContentResponse:
    return await service.get_content(doc_id)


@router.get(
    "/{doc_id}/raw",
    summary="读取原始文件",
    description="返回文档的原始文件字节（不是解析后的文本），供前端按格式渲染原文。",
)
async def get_raw(
    doc_id: str,
    service: DocumentService = Depends(get_document_service),
) -> FileResponse:
    path, media_type = await service.get_raw(doc_id)
    # FileResponse 流式发送，不会把整个文件读进内存
    return FileResponse(path, media_type=media_type, content_disposition_type="inline")


@router.delete(
    "/{doc_id}",
    response_model=DocumentDeleteResponse,
    summary="删除文档",
    description="删除指定文档：向量、元数据、原始文件一并清除。",
)
async def delete(
    doc_id: str,
    caller: Caller = Depends(get_caller),
    service: DocumentService = Depends(get_document_service),
) -> DocumentDeleteResponse:
    # 内部的向量删除是同步的，由 service 自己丢线程池
    return await service.delete_document(doc_id, caller)
