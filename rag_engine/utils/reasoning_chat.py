"""保留百炼 reasoning_content 的 ChatOpenAI 子类

langchain-openai 的 ChatOpenAI 只认 OpenAI 标准字段，百炼兼容模式返回的
reasoning_content 会被直接丢掉。这里只覆盖「流式响应 → LangChain chunk」
这一步，把思考片段放进 additional_kwargs，其余行为（消息转换、工具调用、
usage 统计）完全沿用父类。

注意：依赖 langchain-openai 的私有方法，升级版本时需要回归验证：
用回答模型流式调用一次，确认 chunk.additional_kwargs 里有 reasoning_content。
"""
from langchain_openai import ChatOpenAI


class ReasoningChatOpenAI(ChatOpenAI):
    """在 ChatOpenAI 基础上额外保留 reasoning_content"""

    def _convert_chunk_to_generation_chunk(self, chunk, default_chunk_class,
                                           base_generation_info):
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info)
        if generation_chunk is None:
            return None

        # 与父类相同的兼容写法：普通流在 choices，beta stream 在 chunk.choices
        choices = chunk.get("choices") or (chunk.get("chunk") or {}).get("choices") or []
        for choice in choices:
            reasoning = (choice.get("delta") or {}).get("reasoning_content")
            if reasoning:
                generation_chunk.message.additional_kwargs["reasoning_content"] = reasoning
                break
        return generation_chunk
