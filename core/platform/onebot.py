"""OneBot v11 正向 WebSocket 适配器

作为 WS 客户端连接 NapCat 的 WS 服务端。
仅处理好友私聊消息，支持文本/图片/文件收发。
所有与 NapCat 的交互统一走 call_api()。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

import aiohttp

from core.platform.message import Face, File, Image, JsonMsg, Message, Plain, Reply
from core.platform.base import BasePlatform
from core.pipeline.event import Event

logger = logging.getLogger("ffbot")


class OneBotPlatform(BasePlatform):
    def __init__(self, config: dict):
        super().__init__(config)
        self.ws_url = config.get("ws_url", "ws://127.0.0.1:3001")
        self.access_token = config.get("access_token", "XSVNpVjnQWSUvkC0")

        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task | None = None
        self._running = False
        self._pending: dict[str, asyncio.Future] = {}

        # Bot 自身信息（连接后从 get_login_info 获取）
        self.bot_id: str = ""
        self.bot_name: str = ""

    # ==== 公开属性 ====

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    # ==== 生命周期 ====

    async def start(self) -> None:
        self._running = True
        self._session = aiohttp.ClientSession()
        self._task = asyncio.create_task(self._connect_loop())

    async def stop(self) -> None:
        self._running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()

    # ==== 对外接口 ====

    async def call_api(self, action: str, params: dict | None = None) -> dict:
        """调用任意 OneBot API"""
        if not self.is_connected:
            logger.warning(f"WebSocket 未连接，无法调用: {action}")
            return {}

        echo = str(uuid.uuid4())
        payload = {"action": action, "params": params or {}, "echo": echo}

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[echo] = future

        await self._ws.send_json(payload)

        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning(f"API 调用超时: {action}")
            return {}
        finally:
            self._pending.pop(echo, None)

    async def send_message(self, user_id: int, message: Message) -> str:
        """发送私聊消息，返回消息 ID"""
        segments = self._chain_to_segments(message)
        result = await self.call_api("send_private_msg", {
            "user_id": user_id,
            "message": segments,
        })
        return str(result.get("message_id", ""))

    @staticmethod
    async def test_connection(ws_url: str, access_token: str = "") -> dict:
        """测试连通性，返回 login_info"""
        headers = {}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(ws_url, headers=headers, timeout=5) as ws:
                    await ws.send_json({"action": "get_login_info", "params": {}, "echo": "test"})
                    msg = await asyncio.wait_for(ws.receive(), timeout=5)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if data.get("status") == "failed":
                            raise ConnectionError(data.get("message", "未知错误"))
                        return data.get("data", {})
                    raise ConnectionError("未收到响应")
        except asyncio.TimeoutError:
            raise TimeoutError("连接超时")
        except aiohttp.ClientError as e:
            raise ConnectionError(f"连接失败: {e}")

    # ==== WebSocket 连接与事件处理 ====

    async def _connect_loop(self) -> None:
        while self._running:
            try:
                headers = {}
                if self.access_token:
                    headers["Authorization"] = f"Bearer {self.access_token}"
                self._ws = await self._session.ws_connect(self.ws_url, headers=headers)
                logger.info(f"已连接 NapCat: {self.ws_url}")

                # 先启动接收循环，再调 API（否则无人处理响应）
                recv_task = asyncio.create_task(self._receive_loop())

                login_info = await self.call_api("get_login_info")
                if login_info:
                    self.bot_id = str(login_info.get("user_id", ""))
                    self.bot_name = login_info.get("nickname", "")
                    logger.info(f"Bot: {self.bot_name} ({self.bot_id})")

                await recv_task
            except aiohttp.ClientError as e:
                logger.warning(f"连接失败: {e}，5秒后重连...")
            except asyncio.CancelledError:
                break

            if self._running:
                await asyncio.sleep(5)

    async def _receive_loop(self) -> None:
        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if "echo" in data:
                    self._handle_api_response(data)
                elif data.get("post_type") == "message":
                    asyncio.create_task(self._handle_message_event(data))
            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                break

    def _handle_api_response(self, data: dict) -> None:
        echo = data.get("echo", "")
        future = self._pending.get(echo)
        if future and not future.done():
            future.set_result(data.get("data", {}))

    async def _handle_message_event(self, data: dict) -> None:
        """收到私聊消息 → 直接调回调"""
        if data.get("message_type") != "private":
            return
        
        logger.info(f"{data}")

        sender = data.get("sender", {})
        event = Event(
            message_id=str(data.get("message_id", "")),
            user_id=str(data.get("user_id", "")),
            nickname=sender.get("nickname", ""),
            timestamp=int(data.get("time", 0)),
            message=self._parse_message(data.get("message", [])),
        )

        if self._message_handler:
            await self._message_handler(event)

    # ==== 消息格式转换 ====

    def _parse_message(self, message: list | str) -> Message:
        chain = Message()
        if isinstance(message, str):
            chain.add(Plain(text=message))
            return chain

        for seg in message:
            t = seg.get("type", "")
            d = seg.get("data", {})
            if t == "text":
                text = d.get("text", "")
                if text:
                    chain.add(Plain(text=text))
            elif t == "image":
                chain.add(Image(url=d.get("url", "")))
            elif t == "file":
                chain.add(File(file_id=d.get("file_id", ""), name=d.get("file", "")))
            elif t == "reply":
                chain.add(Reply(message_id=str(d.get("id", ""))))
            elif t == "face":
                raw = d.get("raw", {})
                face_text = raw.get("faceText", "") if isinstance(raw, dict) else ""
                chain.add(Face(face_id=str(d.get("id", "")), face_text=face_text))
            elif t == "json":
                chain.add(JsonMsg(data=d.get("data", "")))
        return chain

    def _chain_to_segments(self, chain: Message) -> list[dict]:
        segments = []
        for c in chain.components:
            if isinstance(c, Plain):
                if c.text:
                    segments.append({"type": "text", "data": {"text": c.text}})
            elif isinstance(c, Image):
                segments.append({"type": "image", "data": {"file": c.file or c.url}})
            elif isinstance(c, File):
                data = {"file": c.file or c.url}
                if c.name:
                    data["name"] = c.name
                segments.append({"type": "file", "data": data})
            elif isinstance(c, Reply):
                segments.append({"type": "reply", "data": {"id": c.message_id}})
            elif isinstance(c, Face):
                segments.append({"type": "face", "data": {"id": c.face_id}})
            elif isinstance(c, JsonMsg):
                segments.append({"type": "json", "data": {"data": c.data}})
        return segments
