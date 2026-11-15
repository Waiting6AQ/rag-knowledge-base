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
    # 轻量模型：给"分类 / 打分 / 改写"这类短输出任务用，生成回答仍走 LLM_MODEL_NAME
    LLM_FAST_MODEL_NAME: str = "openai:qwen3.8-flash"
    LLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    EMBEDDING_MODEL_NAME: str = "qwen3.7-text-embedding"

    # === RAG 参数 ===
    CHUNK_SIZE: int = 500          # 文档分块大小（字符）
    CHUNK_OVERLAP: int = 100       # 相邻块重叠字符数
    # 混合检索返回的候选数：dense 和 sparse 两个分支各召回这么多，融合后也是这么多
    # （Qdrant 的 prefetch limit 与最终 limit 由同一个参数决定），最后交给重排器精排
    TOP_K: int = 5
    # 精排与召回的融合系数 k：score = 1/(k+召回名次) + 1/(k+精排名次)
    # 只按精排排序时，精排的主题偏好会完全覆盖召回信号（实测把 RRF 第 1 的
    # 正确章节压到第 4）；融合后两路名次都保留话语权。设 0 关闭融合，回到纯精排
    RERANK_FUSION_K: int = 10
    # 采样温度。注意：qwen3.8 系列在思考模式下会把小于 0.6 的值强制改成 0.6，
    # 所以这里写 0.1 实际生效是 0.6——不要指望这个值能压低随机性
    TEMPERATURE: float = 0.1
    # LLM 最大输出长度。注意：混合思考模型的思考 token 也计入这里，
    # 所以必须明显大于思考所需量，否则正文会被挤空（之前 2000 就被思考吃光过）
    MAX_TOKENS: int = 8192
    # 混合思考模型（qwen3.8 系列）默认开启思考：多轮对话的指代消解、看图定位这类
    # 空间推理都依赖它，实测关掉后读图准确率明显下降。
    # 先不设 thinking_budget，用日志里打印的实际思考 token 数决定上限
    ENABLE_THINKING: bool = True
    # 回答节点的思考强度：low / medium / xhigh（xhigh 是 qwen3.8 的默认值）。
    # 对应 thinking_budget：low=4096，medium=16384，xhigh=262144。
    # 只作用于回答模型，改写和置信度评估不受影响
    REASONING_EFFORT: str = "low"

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
    # 单次返回的文档正文字符上限（点开查看全文时用）：超出部分截断，并在响应里标记
    DOC_CONTENT_MAX_CHARS: int = 50000

    # === 多模态：回答时附带检索到的原图 ===
    # 开启后，命中的块里若有插图位置，就渲染成 PNG 一起交给模型；
    # 关掉可省流量和首 token 延迟（排查问题时也方便做对照）
    ENABLE_IMAGE_CONTEXT: bool = True
    IMAGE_RENDER_DPI: int = 150

    # === 并发闸门（单进程有效；uvicorn --workers N 时每个进程各有一份） ===
    # 聊天和上传分开计量：聊天主要是等 LLM（I/O），上传要解析 + 嵌入（CPU / 线程池）
    MAX_CONCURRENT_CHATS: int = 8           # 同时在途的聊天请求
    MAX_CONCURRENT_UPLOADS: int = 2         # 同时在途的文档上传
    CONCURRENCY_WAIT_SECONDS: float = 1.5   # 拿不到许可时最多排队多久，超时返回 429

    class Config:
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = "utf-8"


# 全局配置单例
settings = Settings()
