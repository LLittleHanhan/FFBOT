"""OpenAI 兼容 Provider"""

from __future__ import annotations

import logging

from openai import AsyncOpenAI
from .base import BaseProvider, ChatMessage, ChatResponse

logger = logging.getLogger("ffbot")


class OpenAIProvider(BaseProvider):
    def __init__(self, config: dict):
        super().__init__(config)
        self.api_base = config.get("api_base", "https://api.deepseek.com")
        self.api_key = config.get("api_key", "sk-ce011700f9ed446fb75d7fd697159d00")
        self.model = config.get("model", "deepseek-v4-flash")
        self.max_tokens = config.get("max_tokens", 2048)
        self.temperature = config.get("temperature", 0.7)

        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.api_base,
            timeout=config.get("timeout", 60),
        )

    async def chat(self, messages: list[ChatMessage]) -> ChatResponse:
        """调用 OpenAI API - 这里是真正需要 await 的地方（网络IO）"""
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=[m.to_dict() for m in messages],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        choice = response.choices[0]
        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return ChatResponse(content=choice.message.content or "", usage=usage)
