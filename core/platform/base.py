"""平台基类"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Callable, Coroutine, Any

if TYPE_CHECKING:
    from core.pipeline.event import Event
    from core.platform.message import Message

EventHandler = Callable[["Event"], Coroutine[Any, Any, None]]


class BasePlatform(abc.ABC):
    def __init__(self, config: dict):
        self.config = config
        self._message_handler: EventHandler | None = None

    def on_message(self, handler: EventHandler) -> None:
        self._message_handler = handler

    @abc.abstractmethod
    async def start(self) -> None: ...

    @abc.abstractmethod
    async def stop(self) -> None: ...

    @abc.abstractmethod
    async def send_message(self, user_id: int, message: "Message") -> str: ...
