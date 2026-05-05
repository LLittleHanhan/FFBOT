"""生命周期管理器

负责整个应用的启动、运行、停止、配置热重载。
"""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path
from typing import Any

import yaml

from core.pipeline.pipeline import Pipeline
from core.pipeline.event import Event
from core.pipeline.preprocess import PreprocessStage
from core.pipeline.process import ProcessStage
from core.pipeline.respond import RespondStage
from core.platform.onebot import OneBotPlatform
from core.provider.openai_provider import OpenAIProvider
from core.storage import StorageManager
from core.web_server import WebServer

logger = logging.getLogger("ffbot")


class Lifecycle:
    def __init__(self, config: dict[str, Any]):
        self.config = config

        # 存储层
        storage_config = config.get("storage", {})
        self.storage = StorageManager(
            db_path=storage_config.get("db_path", "data/ffbot.db")
        )

        # 核心组件
        self.provider = self._create_provider()
        self.platform = OneBotPlatform(config.get("platform", {}).get("onebot", {}))
        self.pipeline = self._create_pipeline()

        self.platform.on_message(self._on_message)

        web_port = config.get("web", {}).get("port", 8080)
        self.web_server = WebServer(self, port=web_port)

    async def start(self) -> None:
        logger.info("FFBot 正在启动...")
        await self.storage.initialize()
        await self.platform.start()
        await self.web_server.start()
        logger.info("FFBot 启动完成!")
        await self._wait_for_shutdown()

    async def stop(self) -> None:
        logger.info("FFBot 正在停止...")
        await self.web_server.stop()
        await self.platform.stop()
        await self.storage.close()
        logger.info("FFBot 已停止")

    def get_status(self) -> dict:
        return {
            "ws_connected": self.platform.is_connected,
            "ws_url": self.platform.ws_url,
            "model": self.provider.model,
            "api_base": self.provider.api_base,
        }

    async def reload_config(self, new_config: dict[str, Any]) -> None:
        config_path = Path("config.yaml")
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(new_config, f, allow_unicode=True, default_flow_style=False)

        self.config = new_config
        self.provider = self._create_provider()
        self.pipeline = self._create_pipeline()

        platform_config = new_config.get("platform", {}).get("onebot", {})
        new_ws_url = platform_config.get("ws_url", "")
        new_token = platform_config.get("access_token", "")
        if (new_ws_url != self.platform.ws_url or
                new_token != self.platform.access_token):
            await self.platform.stop()
            self.platform = OneBotPlatform(platform_config)
            self.platform.on_message(self._on_message)
            await self.platform.start()

        logger.info("配置热重载完成")

    async def test_platform(self, ws_url: str, access_token: str = "") -> dict:
        return await OneBotPlatform.test_connection(ws_url, access_token)

    async def test_provider(self, config: dict | None = None) -> dict:
        provider = OpenAIProvider(config) if config else self.provider
        response = await provider.test_connection()
        return {"content": response.content, "usage": response.usage}

    async def _on_message(self, event: Event) -> None:
        await self.pipeline.execute(event)

    def _create_provider(self) -> OpenAIProvider:
        return OpenAIProvider(self.config.get("provider", {}).get("openai", {}))

    def _create_pipeline(self) -> Pipeline:
        system_prompt = self.config.get("conversation", {}).get("system_prompt", "")
        pipeline = Pipeline()
        pipeline.add_stage(PreprocessStage(self.storage))
        pipeline.add_stage(ProcessStage(
            provider=self.provider,
            system_prompt=system_prompt,
        ))
        pipeline.add_stage(RespondStage(self.platform, self.storage))
        return pipeline

    async def _wait_for_shutdown(self) -> None:
        stop_event = asyncio.Event()

        def _signal_handler():
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                pass

        await stop_event.wait()
        await self.stop()
