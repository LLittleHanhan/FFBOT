"""预处理 - 持久化、鉴权、文本提取"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.pipeline.base import PipelineStage

if TYPE_CHECKING:
    from core.pipeline.event import Event
    from core.storage import StorageManager


class PreprocessStage(PipelineStage):
    def __init__(self, storage: "StorageManager"):
        self.storage = storage

    async def process(self, event: "Event") -> bool:
        await self.storage.upsert_user(event.user_id, event.nickname)

        await self.storage.save_message(
            message_id=event.message_id,
            user_id=event.user_id,
            content=event.to_json(),
        )

        if not await self.storage.is_allowed(event.user_id):
            event.should_respond = False
            return False

        plain_text = event.message.get_plain_text().strip()
        if not plain_text:
            event.should_respond = False
            return False

        event.metadata["plain_text"] = plain_text
        return True
