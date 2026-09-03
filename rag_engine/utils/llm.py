"""
LLM 工厂

统一创建大语言模型实例，所有配置从 config 读取。
所有 LLM 实例统一带容错：
1. with_retry：网络类异常与限流自动重试（指数退避 + 抖动）
2. with_fallbacks：重试耗尽后切换备用模型（额度 403 按模型计，备用模型可续命）
"""
from langchain.chat_models import init_chat_model
from openai import APIConnectionError, RateLimitError
from core.config import settings


def _with_retry(model):
    """给 LLM 实例挂重试：网络/限流类异常指数退避重试 3 次"""
    return model.with_retry(
        retry_if_exception_type=(APIConnectionError, RateLimitError),
        wait_exponential_jitter=True,
        stop_after_attempt=3,
    )


def _with_fallback(model):
    """挂备用模型：主模型重试耗尽后自动切换"""
    backup = init_chat_model(
        settings.LLM_BACKUP_MODEL_NAME,
        api_key=settings.DASHSCOPE_API_KEY,
        base_url=settings.LLM_BASE_URL,
        temperature=settings.TEMPERATURE,
        max_tokens=settings.MAX_TOKENS,
    )
    return model.with_fallbacks([backup])


def create_llm(temperature: float | None = None):
    """创建 LLM 实例，temperature 为 None 则使用默认配置"""
    model = init_chat_model(
        settings.LLM_MODEL_NAME,
        api_key=settings.DASHSCOPE_API_KEY,
        base_url=settings.LLM_BASE_URL,
        temperature=temperature if temperature is not None else settings.TEMPERATURE,
        max_tokens=settings.MAX_TOKENS,
    )
    return _with_fallback(_with_retry(model))
