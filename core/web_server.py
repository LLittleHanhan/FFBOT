"""Web Server - HTTP API 路由层"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from core.lifecycle import Lifecycle

logger = logging.getLogger("ffbot")


class WebServer:
    def __init__(self, lifecycle: "Lifecycle", port: int = 8080):
        self.lifecycle = lifecycle
        self.port = port
        self.app = web.Application()
        self._runner: web.AppRunner | None = None
        self._setup_routes()

    def _setup_routes(self) -> None:
        r = self.app.router
        r.add_get("/", self._handle_index)
        r.add_get("/api/status", self._handle_status)
        r.add_get("/api/config", self._handle_get_config)
        r.add_post("/api/config", self._handle_save_config)
        r.add_post("/api/test/platform", self._handle_test_platform)
        r.add_post("/api/test/provider", self._handle_test_provider)
        r.add_post("/api/debug/call", self._handle_debug_call)
        # 用户管理
        r.add_get("/api/users", self._handle_get_users)
        r.add_post("/api/users/allow", self._handle_set_allowed)
        # 对话记录
        r.add_post("/api/messages", self._handle_get_messages)
        r.add_post("/api/messages/delete", self._handle_delete_messages)
        static_dir = Path(__file__).parent.parent / "static"
        if static_dir.exists():
            r.add_static("/static", static_dir)

    async def start(self) -> None:
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await site.start()
        logger.info(f"Web 控制台: http://localhost:{self.port}")

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    async def _handle_index(self, request: web.Request) -> web.Response:
        index_path = Path(__file__).parent.parent / "static" / "index.html"
        return web.FileResponse(index_path)

    async def _handle_status(self, request: web.Request) -> web.Response:
        status = self.lifecycle.get_status()
        status["bot_name"] = self.lifecycle.platform.bot_name
        return web.json_response(status)

    async def _handle_get_config(self, request: web.Request) -> web.Response:
        return web.json_response(self.lifecycle.config)

    async def _handle_save_config(self, request: web.Request) -> web.Response:
        try:
            new_config = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"ok": False, "error": "无效的 JSON"}, status=400)
        try:
            await self.lifecycle.reload_config(new_config)
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)})

    async def _handle_test_platform(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            body = {}
        ws_url = body.get("ws_url", self.lifecycle.platform.ws_url)
        token = body.get("access_token", self.lifecycle.platform.access_token)
        try:
            await self.lifecycle.test_platform(ws_url, token)
            return web.json_response({"ok": True, "message": "连接成功"})
        except (ConnectionError, TimeoutError) as e:
            return web.json_response({"ok": False, "error": str(e)})

    async def _handle_test_provider(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            body = {}
        try:
            config = body if body else None
            result = await self.lifecycle.test_provider(config)
            return web.json_response({"ok": True, "message": f"模型回复: {result['content']}"})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)})

    async def _handle_debug_call(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"ok": False, "error": "无效的 JSON"}, status=400)
        action = body.get("action", "")
        params = body.get("params", {})
        if not action:
            return web.json_response({"ok": False, "error": "缺少 action"}, status=400)
        try:
            result = await self.lifecycle.platform.call_api(action, params)
            return web.json_response({"ok": True, "data": result})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)})

    # ========== 用户管理 ==========

    async def _handle_get_users(self, request: web.Request) -> web.Response:
        users = await self.lifecycle.storage.get_all_users()
        return web.json_response({"ok": True, "users": users})

    async def _handle_set_allowed(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"ok": False, "error": "无效的 JSON"}, status=400)
        user_id = body.get("user_id")
        allowed = body.get("allowed")
        if not user_id or allowed is None:
            return web.json_response({"ok": False, "error": "缺少 user_id 或 allowed"}, status=400)
        await self.lifecycle.storage.set_allowed(user_id, bool(allowed))
        return web.json_response({"ok": True})

    # ========== 对话记录 ==========

    async def _handle_get_messages(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"ok": False, "error": "无效的 JSON"}, status=400)
        user_id = body.get("user_id")
        if not user_id:
            return web.json_response({"ok": False, "error": "缺少 user_id"}, status=400)
        messages = await self.lifecycle.storage.get_messages(
            user_id=user_id,
            limit=body.get("limit"),
            start_time=body.get("start_time"),
            end_time=body.get("end_time"),
        )
        return web.json_response({"ok": True, "messages": messages})

    async def _handle_delete_messages(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"ok": False, "error": "无效的 JSON"}, status=400)
        user_id = body.get("user_id")
        if not user_id:
            return web.json_response({"ok": False, "error": "缺少 user_id"}, status=400)
        message_ids = body.get("message_ids")  # 可选，为空则删全部
        count = await self.lifecycle.storage.delete_messages(user_id, message_ids)
        return web.json_response({"ok": True, "deleted": count})
