"""
文档管理路由

提供文档的上传、列表、删除功能。
上传的文档经分块→嵌入后写入向量库，元数据登记在 PostgreSQL。
"""
from fastapi import APIRouter, File, UploadFile, Depends
from core.dependencies import get_document_service
from models.document import (
    DocumentUploadResponse,
    DocumentListResponse,
    DocumentDeleteResponse,
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
    service: DocumentService = Depends(get_document_service),
) -> DocumentUploadResponse:
    return await service.upload(file)


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


@router.delete(
    "/{doc_id}",
    response_model=DocumentDeleteResponse,
    summary="删除文档",
    description="删除指定文档：向量、元数据、原始文件一并清除。",
)
async def delete(
    doc_id: str,
    service: DocumentService = Depends(get_document_service),
) -> DocumentDeleteResponse:
    # 内部的向量删除是同步的，由 service 自己丢线程池
    return await service.delete_document(doc_id)
