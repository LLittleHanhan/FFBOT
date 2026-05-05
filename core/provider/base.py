"""Provider 基类和数据模型"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass
class ChatMessage:
    """一条对话消息"""
    role: str   # system, user, assistant
    content: str = ""

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class ChatResponse:
    """LLM 返回的响应"""
    content: str = ""
    usage: dict[str, int] = field(default_factory=dict)


class BaseProvider(abc.ABC):
    """LLM Provider 基类，实现 chat() 即可"""

    def __init__(self, config: dict):
        self.config = config

    @abc.abstractmethod
    async def chat(self, messages: list[ChatMessage]) -> ChatResponse: ...

    async def test_connection(self) -> ChatResponse:
        """测试 LLM 连通性，成功返回 ChatResponse，失败抛异常"""
        return await self.chat([ChatMessage(role="user", content="请回复'ok'")])
