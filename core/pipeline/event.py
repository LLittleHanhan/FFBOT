"""事件 - Pipeline 处理的基本单元"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.platform.message import Message


class Event:
    __slots__ = ("message_id", "user_id", "nickname", "timestamp",
                 "message", "metadata", "response", "should_respond")

    def __init__(
        self,
        message_id: str = "",
        user_id: str = "",
        nickname: str = "",
        timestamp: int = 0,
        message: "Message | None" = None,
    ):
        from core.platform.message import Message as M
        self.message_id = message_id
        self.user_id = user_id
        self.nickname = nickname or user_id
        self.timestamp = timestamp
        self.message = message or M()
        self.metadata: dict = {}
        self.response: "Message | None" = None
        self.should_respond: bool = True

    def to_json(self) -> str:
        """序列化，用于持久化"""
        return json.dumps({
            "message_id": self.message_id,
            "user_id": self.user_id,
            "nickname": self.nickname,
            "timestamp": self.timestamp,
            "message": [c.to_dict() for c in self.message.components],
        }, ensure_ascii=False)

    def __repr__(self) -> str:
        return f"Event(message_id={self.message_id}, user_id={self.user_id})"
