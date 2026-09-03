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
    TOP_K: int = 5                 # 向量检索返回数量
    BM25_K: int = 3                # BM25 关键词检索返回数量
    TEMPERATURE: float = 0.1       # LLM 温度，越低越保守（RAG 需要确定性回答）
    MAX_TOKENS: int = 2000         # LLM 最大输出长度（1000 时详细回答被截断）

    # === 存储路径（基于项目根目录，不受 VS Code 启动位置影响） ===
    CHROMA_PERSIST_DIR: str = str(BASE_DIR / "data" / "chroma_db")
    CHECKPOINT_DB_PATH: str = str(BASE_DIR / "data" / "checkpoints.db")
    APP_DB_PATH: str = str(BASE_DIR / "data" / "app.db")
    UPLOAD_DIR: str = str(BASE_DIR / "data" / "uploads")

    # === 文件上传限制 ===
    ALLOWED_EXTENSIONS: list[str] = [".txt", ".pdf", ".md", ".docx", ".xlsx"]
    MAX_UPLOAD_SIZE_MB: int = 20

    class Config:
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = "utf-8"


# 全局配置单例
settings = Settings()
