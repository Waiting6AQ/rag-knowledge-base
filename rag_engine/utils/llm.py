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

# 统一注入是否开启思考模式（qwen3.8 是混合思考模型，默认开启，见 config 里的说明）
_EXTRA_BODY = {"enable_thinking": settings.ENABLE_THINKING}
# 置信度评估专用：只需要核对材料，不需要思考。实测开关两种模式的区分度一致
# （正确 0.6 / 错误 0.4），但关掉后单次调用从 8~12s 降到 0.5s 左右
_NO_THINKING = {"enable_thinking": False}


def _with_retry(model):
    """给 LLM 实例挂重试：网络/限流类异常指数退避重试 3 次"""
    return model.with_retry(
        retry_if_exception_type=(APIConnectionError, RateLimitError),
        wait_exponential_jitter=True,
        stop_after_attempt=3,
    )


def _with_fallback(model, model_kwargs: dict | None = None,
                   reasoning_effort: str | None = None,
                   extra_body: dict | None = None):
    """挂备用模型：主模型重试耗尽后自动切换

    model_kwargs 必须一起传：备用模型不带同样的参数的话，
    降级后 response_format 就丢了，JSON 模式失效。
    reasoning_effort / extra_body 同理：主模型关思考、备用模型开思考的话，
    降级后的行为和速度会突然变化。
    """
    backup = init_chat_model(
        settings.LLM_BACKUP_MODEL_NAME,
        api_key=settings.DASHSCOPE_API_KEY,
        base_url=settings.LLM_BASE_URL,
        temperature=settings.TEMPERATURE,
        max_tokens=settings.MAX_TOKENS,
        model_kwargs=model_kwargs or {},
        reasoning_effort=reasoning_effort,
        extra_body=extra_body or _EXTRA_BODY,
        stream_usage=True,
    )
    return model.with_fallbacks([backup])


def _create(model_name: str, temperature: float | None = None,
            reasoning_effort: str | None = None,
            extra_body: dict | None = None):
    """按模型名创建实例，统一挂重试与备用模型"""
    model = init_chat_model(
        model_name,
        api_key=settings.DASHSCOPE_API_KEY,
        base_url=settings.LLM_BASE_URL,
        temperature=temperature if temperature is not None else settings.TEMPERATURE,
        max_tokens=settings.MAX_TOKENS,
        reasoning_effort=reasoning_effort,
        extra_body=extra_body or _EXTRA_BODY,
        # 自定义 base_url 时 LangChain 默认不带 usage；打开后流式响应的最后一个
        # chunk 才会带 token 用量（含思考 token），用于统计思考开销
        stream_usage=True,
    )
    return _with_fallback(_with_retry(model), reasoning_effort=reasoning_effort,
                          extra_body=extra_body)


def create_llm(temperature: float | None = None):
    """创建 LLM 实例：回答节点专用，思考强度取 REASONING_EFFORT"""
    return _create(settings.LLM_MODEL_NAME, temperature, settings.REASONING_EFFORT)


def create_fast_llm(temperature: float | None = None):
    """创建轻量模型实例（判断 / 打分这类短输出任务）

    LLM_FAST_MODEL_NAME 未配置时回落到主模型，行为与改造前完全一致。
    备用模型仍是 LLM_BACKUP_MODEL_NAME：轻量模型失败时退回主模型，慢但可用。
    这里固定关闭思考：置信度评估只需核对给定材料，实测开关两种模式对
    正确/错误答案的区分度一致，但关掉后耗时从 8~12s 降到 0.5s 左右。
    回答节点仍保持思考，不受影响。
    """
    return _create(settings.LLM_FAST_MODEL_NAME or settings.LLM_MODEL_NAME,
                   temperature, extra_body=_NO_THINKING)


def create_fast_json_llm():
    """JSON Mode 的轻量模型（改写节点：一次调用产出"改写结果 / 闲聊回复"两种形态）

    改写是"把口语规范化"的确定性任务，采样带来的随机性会直接传导到检索。
    注意 temperature 压不住这里的随机性：qwen3.8 思考模式会把 <0.6 的值强制改成 0.6。
    不设 temperature=0：官方文档明确不建议取 0，且也做不到完全复现。
    """
    kwargs = {"response_format": {"type": "json_object"}}
    model = init_chat_model(
        settings.LLM_FAST_MODEL_NAME or settings.LLM_MODEL_NAME,
        api_key=settings.DASHSCOPE_API_KEY,
        base_url=settings.LLM_BASE_URL,
        temperature=settings.TEMPERATURE,
        max_tokens=settings.MAX_TOKENS,
        model_kwargs=kwargs,
        extra_body=_EXTRA_BODY,
    )
    return _with_fallback(_with_retry(model), model_kwargs=kwargs)


def create_json_llm():
    """创建 JSON Mode 的 LLM（强制输出合法 JSON）

    用于改写节点：它一次调用要产出两种结果（改写后的查询 / 闲聊回复），
    必须靠结构化字段区分，不能用自由文本。
    """
    kwargs = {"response_format": {"type": "json_object"}}
    model = init_chat_model(
        settings.LLM_MODEL_NAME,
        api_key=settings.DASHSCOPE_API_KEY,
        base_url=settings.LLM_BASE_URL,
        temperature=settings.TEMPERATURE,
        max_tokens=settings.MAX_TOKENS,
        model_kwargs=kwargs,
        extra_body=_EXTRA_BODY,
    )
    return _with_fallback(_with_retry(model), model_kwargs=kwargs)
