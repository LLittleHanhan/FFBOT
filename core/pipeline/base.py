"""Pipeline Stage 基类"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.pipeline.event import Event


class PipelineStage(abc.ABC):
    @abc.abstractmethod
    async def process(self, event: "Event") -> bool: ...
