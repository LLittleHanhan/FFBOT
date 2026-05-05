"""消息定义 - 支持文本、图片、文件、回复、表情、JSON卡片"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Plain:
    text: str = ""

    def to_dict(self) -> dict:
        return {"type": "text", "data": {"text": self.text}}

    def __str__(self) -> str:
        return self.text


@dataclass
class Image:
    url: str = ""
    file: str = ""

    def to_dict(self) -> dict:
        return {"type": "image", "data": {"url": self.url, "file": self.file}}


@dataclass
class File:
    file_id: str = ""
    name: str = ""
    file: str = ""

    def to_dict(self) -> dict:
        return {"type": "file", "data": {"file_id": self.file_id, "name": self.name, "file": self.file}}


@dataclass
class Reply:
    message_id: str = ""

    def to_dict(self) -> dict:
        return {"type": "reply", "data": {"id": self.message_id}}


@dataclass
class Face:
    face_id: str = ""
    face_text: str = ""

    def to_dict(self) -> dict:
        return {"type": "face", "data": {"id": self.face_id, "face_text": self.face_text}}

    def __str__(self) -> str:
        return f"[{self.face_text}]" if self.face_text else f"[表情{self.face_id}]"


@dataclass
class JsonMsg:
    data: str = ""

    def to_dict(self) -> dict:
        return {"type": "json", "data": {"data": self.data}}

    def get_summary(self) -> str:
        import json as _json
        try:
            obj = _json.loads(self.data)
            meta = obj.get("meta", {})
            for key in meta:
                item = meta[key]
                if isinstance(item, dict):
                    title = item.get("title", "")
                    desc = item.get("desc", "")
                    url = item.get("qqdocurl", item.get("jumpUrl", item.get("url", "")))
                    parts = [p for p in [title, desc, url] if p]
                    if parts:
                        return " | ".join(parts)
            prompt = obj.get("prompt", "")
            if prompt:
                return f"[卡片] {prompt}"
        except (_json.JSONDecodeError, TypeError, AttributeError):
            pass
        return "[JSON卡片]"

    def __str__(self) -> str:
        return self.get_summary()


@dataclass
class Message:
    """消息 - 由多个组件组成"""
    components: list = field(default_factory=list)

    def add(self, component) -> "Message":
        self.components.append(component)
        return self

    def get_plain_text(self) -> str:
        parts = []
        for c in self.components:
            if isinstance(c, Plain):
                parts.append(c.text)
            elif isinstance(c, Face):
                parts.append(str(c))
            elif isinstance(c, JsonMsg):
                parts.append(str(c))
        return "".join(parts)

    def get_images(self) -> list[Image]:
        return [c for c in self.components if isinstance(c, Image)]

    def get_files(self) -> list[File]:
        return [c for c in self.components if isinstance(c, File)]

    def get_reply(self) -> Reply | None:
        for c in self.components:
            if isinstance(c, Reply):
                return c
        return None
