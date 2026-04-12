"""
将 OpenAI 兼容接口返回的 reasoning_content 写入 AIMessage.additional_kwargs。

对齐 langchain 侧社区修复思路：https://github.com/langchain-ai/langchain/pull/35065
（官方 ChatOpenAI 曾丢弃 DeepSeek / vLLM 等返回的 reasoning_content。）

在创建 ChatOpenAI 之前调用：apply_langchain_openai_reasoning_content_patch()
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_applied: bool = False


def apply_langchain_openai_reasoning_content_patch() -> None:
    """Monkey-patch langchain_openai.chat_models.base 中的两条转换函数，各执行一次即可。"""
    global _applied
    if _applied:
        return

    from langchain_core.messages import AIMessage, AIMessageChunk

    from langchain_openai.chat_models import base as lb

    _orig_dict = lb._convert_dict_to_message
    _orig_delta = lb._convert_delta_to_message_chunk

    def _pick_reasoning(_dict: Mapping[str, Any]) -> Any | None:
        if "reasoning_content" in _dict and _dict["reasoning_content"] is not None:
            return _dict["reasoning_content"]
        if "thinking" in _dict and _dict["thinking"] is not None:
            return _dict["thinking"]
        return None

    def _convert_dict_to_message(_dict: Mapping[str, Any]):
        msg = _orig_dict(_dict)
        rc = _pick_reasoning(_dict)
        if isinstance(msg, AIMessage) and rc is not None:
            msg.additional_kwargs["reasoning_content"] = rc
        return msg

    def _convert_delta_to_message_chunk(_dict: Mapping[str, Any], default_class: Any):
        chunk = _orig_delta(_dict, default_class)
        rc = _pick_reasoning(_dict)
        if isinstance(chunk, AIMessageChunk) and rc is not None:
            chunk.additional_kwargs["reasoning_content"] = (
                rc if isinstance(rc, str) else str(rc)
            )
        return chunk

    lb._convert_dict_to_message = _convert_dict_to_message
    lb._convert_delta_to_message_chunk = _convert_delta_to_message_chunk
    _applied = True
