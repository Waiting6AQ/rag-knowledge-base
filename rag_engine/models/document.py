"""
文档管理相关 Pydantic 数据模型

这些模型用于 FastAPI 的请求校验和响应格式化：
- FastAPI 会自动根据模型校验请求数据（类型不对直接返回 422）
- response_model 参数会根据模型过滤响应字段（只返回模型中声明的字段）
- 自动生成 OpenAPI 文档（Swagger 页面可以看到所有字段说明）
"""
from pydantic import BaseModel, Field


# ---------- 上传响应 ----------
class DocumentUploadResponse(BaseModel):
    """上传文档后返回的信息"""
    doc_id: str                                  # 系统生成的唯一文档 ID（UUID）
    filename: str                                # 实际保存的文件名（同名时带 (1) 后缀）
    file_type: str                               # 文件类型（txt / pdf / md）
    chunk_count: int                             # 分成了多少个文本块
    renamed: bool = False                        # 是否因重名被重命名
    status: str = "indexed"                      # 处理状态，成功都是 "indexed"


# ---------- 列表响应 ----------
class DocumentInfo(BaseModel):
    """文档列表中每个文档的摘要信息"""
    doc_id: str                                  # 文档 ID
    filename: str                                # 文件名
    file_type: str                               # 文件类型
    chunk_count: int                             # 文本块数量
    upload_time: str                             # 上传时间（ISO 格式字符串）


class DocumentListResponse(BaseModel):
    """文档列表接口的完整响应"""
    total: int                                   # 文档总数
    documents: list[DocumentInfo]                # 文档摘要列表


# ---------- 删除响应 ----------
class DocumentDeleteResponse(BaseModel):
    """删除文档后返回的信息"""
    doc_id: str                                  # 被删除的文档 ID
    status: str = "deleted"                      # 状态，固定为 "deleted"
    chunks_removed: int                          # 从向量库中移除的文本块数量
