"""
应用配置模块

通过 pydantic-settings 自动加载 .env 文件和环境变量，
所有配置集中管理，其他模块导入 settings 单例即可。
"""
from pathlib import Path
from pydantic_settings import BaseSettings

# 项目根目录，基于当前文件位置推算，不受启动位置影响
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """应用配置，属性名与 .env 变量名一一对应"""

    # === DashScope API（阿里云） ===
    DASHSCOPE_API_KEY: str
    LLM_MODEL_NAME: str = "openai:qwen3.7-max-2026-06-08"
    LLM_BACKUP_MODEL_NAME: str = "openai:qwen3.7-max-2026-05-20"
    LLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    EMBEDDING_MODEL_NAME: str = "qwen3.7-text-embedding"

    # === RAG 参数 ===
    CHUNK_SIZE: int = 500          # 文档分块大小（字符）
    CHUNK_OVERLAP: int = 100       # 相邻块重叠字符数
    # 混合检索返回的候选数：dense 和 sparse 两个分支各召回这么多，融合后也是这么多
    # （Qdrant 的 prefetch limit 与最终 limit 由同一个参数决定），最后交给重排器精排
    TOP_K: int = 5
    TEMPERATURE: float = 0.1       # LLM 温度，越低越保守（RAG 需要确定性回答）
    MAX_TOKENS: int = 2000         # LLM 最大输出长度（1000 时详细回答被截断）

    # === PostgreSQL（会话状态 + 对话元数据） ===
    # 必填：不配则启动即报错（fail-fast，与 DASHSCOPE_API_KEY 一致）
    # 本地开发连 localhost；容器内由 compose 注入服务名 postgres（见 docker-compose.yml）
    POSTGRES_DSN: str
    PG_POOL_MIN: int = 2           # psycopg 池下限（LangGraph checkpoint 用）
    PG_POOL_MAX: int = 10          # psycopg 池上限

    # === Qdrant（向量存储） ===
    # 本地开发连 localhost；容器内由 compose 注入服务名（见 docker-compose.yml）
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "rag_documents"

    # === 存储路径（基于项目根目录，不受 VS Code 启动位置影响） ===
    UPLOAD_DIR: str = str(BASE_DIR / "data" / "uploads")

    # === 文件上传限制 ===
    ALLOWED_EXTENSIONS: list[str] = [".txt", ".pdf", ".md", ".docx", ".xlsx"]
    MAX_UPLOAD_SIZE_MB: int = 20

    class Config:
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = "utf-8"


# 全局配置单例
settings = Settings()
