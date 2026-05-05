"""Pipeline 编排器"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.pipeline.base import PipelineStage

if TYPE_CHECKING:
    from core.pipeline.event import Event


class Pipeline:
    def __init__(self):
        self._stages: list[PipelineStage] = []

    def add_stage(self, stage: PipelineStage) -> None:
        self._stages.append(stage)

    async def execute(self, event: "Event") -> None:
        for stage in self._stages:
            if not await stage.process(event):
                break
