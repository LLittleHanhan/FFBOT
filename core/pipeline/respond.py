"""发送回复并持久化"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.pipeline.base import PipelineStage

if TYPE_CHECKING:
    from core.pipeline.event import Event
    from core.platform.base import BasePlatform
    from core.storage import StorageManager

logger = logging.getLogger("ffbot")


class RespondStage(PipelineStage):
    def __init__(self, platform: "BasePlatform", storage: "StorageManager"):
        self.platform = platform
        self.storage = storage

    async def process(self, event: "Event") -> bool:
        if not event.should_respond or not event.response:
            return True
        try:
            await self.platform.send_message(int(event.user_id), event.response)
            reply_text = event.metadata.get("reply_text", "")
            if reply_text:
                await self.storage.save_reply(event.message_id, reply_text)
        except Exception as e:
            logger.error(f"发送响应失败: {e}")
        return True
