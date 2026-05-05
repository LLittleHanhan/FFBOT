"""LLM 调用"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.platform.message import Message, Plain
from core.pipeline.base import PipelineStage
from core.provider.base import ChatMessage

if TYPE_CHECKING:
    from core.pipeline.event import Event
    from core.provider.base import BaseProvider

logger = logging.getLogger("ffbot")


class ProcessStage(PipelineStage):
    def __init__(self, provider: "BaseProvider", system_prompt: str = ""):
        self.provider = provider
        self.system_prompt = system_prompt

    async def process(self, event: "Event") -> bool:
        plain_text = event.metadata.get("plain_text", "")
        if not plain_text:
            return False

        messages: list[ChatMessage] = []
        if self.system_prompt:
            messages.append(ChatMessage(role="system", content=self.system_prompt))
        messages.append(ChatMessage(role="user", content=plain_text))

        try:
            response = await self.provider.chat(messages)
            reply_text = response.content
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            reply_text = "抱歉，我暂时无法回复，请稍后再试。"

        event.metadata["reply_text"] = reply_text
        event.response = Message([Plain(text=reply_text)])
        return True
