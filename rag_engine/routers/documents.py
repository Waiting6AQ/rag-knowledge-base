"""
文档管理路由

提供文档的上传、列表、删除功能。
上传的文档经分块→嵌入后存入 ChromaDB，供 RAG 问答检索使用。
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
    return service.list_documents()


@router.delete(
    "/{doc_id}",
    response_model=DocumentDeleteResponse,
    summary="删除文档",
    description="从向量库中删除指定文档及其所有分块。",
)
async def delete(
    doc_id: str,
    service: DocumentService = Depends(get_document_service),
) -> DocumentDeleteResponse:
    return service.delete_document(doc_id)
