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
def list_documents(
    service: DocumentService = Depends(get_document_service),
) -> DocumentListResponse:
    # 纯同步实现（ChromaDB 本地查询）：写 def 由 FastAPI 自动放入线程池执行；
    # 若声明为 async def，同步查询会阻塞事件循环线程，卡住所有并发请求
    return service.list_documents()


@router.delete(
    "/{doc_id}",
    response_model=DocumentDeleteResponse,
    summary="删除文档",
    description="从向量库中删除指定文档及其所有分块。",
)
def delete(
    doc_id: str,
    service: DocumentService = Depends(get_document_service),
) -> DocumentDeleteResponse:
    # 同上：内部是同步的 ChromaDB 查询 + 文件删除，交给线程池执行
    return service.delete_document(doc_id)
