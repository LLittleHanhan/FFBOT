"""存储管理器 - 基于 aiosqlite 的异步 SQLite 持久化"""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger("ffbot")

SCHEMA_VERSION = 2

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id     TEXT PRIMARY KEY,
    nickname    TEXT NOT NULL DEFAULT '',
    is_allowed  INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL DEFAULT (unixepoch('subsec')),
    updated_at  REAL NOT NULL DEFAULT (unixepoch('subsec'))
);

CREATE TABLE IF NOT EXISTS messages (
    message_id  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    content     TEXT NOT NULL,
    reply       TEXT DEFAULT NULL,
    created_at  REAL NOT NULL DEFAULT (unixepoch('subsec'))
);
CREATE INDEX IF NOT EXISTS idx_messages_user_time
    ON messages(user_id, created_at);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
"""


class StorageManager:
    """异步 SQLite 存储管理器"""

    def __init__(self, db_path: str = "data/ffbot.db"):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(SCHEMA_SQL)

        async with self._db.execute("SELECT COUNT(*) FROM schema_version") as cur:
            row = await cur.fetchone()
            if row[0] == 0:
                await self._db.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (SCHEMA_VERSION,),
                )
        await self._db.commit()
        logger.info(f"StorageManager 初始化完成: {self.db_path}")

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # ========== 消息 ==========

    async def save_message(self, message_id: str, user_id: str, content: str) -> None:
        """保存用户消息"""
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO messages (message_id, user_id, content) VALUES (?, ?, ?)",
            (message_id, user_id, content),
        )
        await self._db.commit()

    async def save_reply(self, message_id: str, reply: str) -> None:
        """保存 bot 回复到对应的消息记录"""
        assert self._db is not None
        await self._db.execute(
            "UPDATE messages SET reply = ? WHERE message_id = ?",
            (reply, message_id),
        )
        await self._db.commit()

    async def get_messages(
        self,
        user_id: str,
        limit: int | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[dict]:
        """获取与某用户的对话记录，按时间升序

        Args:
            user_id: 对方用户ID（必填）
            limit: 最近 N 条（可选）
            start_time: 起始时间，如 "2026-05-04 20:00:00"（可选）
            end_time: 结束时间，如 "2026-05-04 22:00:00"（可选）
        """
        from datetime import datetime

        assert self._db is not None

        conditions = ["user_id = ?"]
        params: list = [user_id]

        if start_time is not None:
            ts = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S").timestamp()
            conditions.append("created_at >= ?")
            params.append(ts)
        if end_time is not None:
            ts = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S").timestamp()
            conditions.append("created_at <= ?")
            params.append(ts)

        where = " AND ".join(conditions)
        sql = f"SELECT message_id, user_id, content, reply, created_at FROM messages WHERE {where} ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        async with self._db.execute(sql, params) as cur:
            rows = await cur.fetchall()

        return [dict(r) for r in reversed(rows)]

    async def delete_messages(self, user_id: str, message_ids: list[str] | None = None) -> int:
        """删除对话记录

        Args:
            user_id: 用户ID（必填）
            message_ids: 指定消息ID列表（可选，为空则删除该用户全部记录）
        Returns:
            删除的条数
        """
        assert self._db is not None
        if message_ids:
            placeholders = ",".join("?" * len(message_ids))
            sql = f"DELETE FROM messages WHERE user_id = ? AND message_id IN ({placeholders})"
            cursor = await self._db.execute(sql, [user_id, *message_ids])
        else:
            cursor = await self._db.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        await self._db.commit()
        return cursor.rowcount

    # ========== 用户管理 ==========

    async def upsert_user(self, user_id: str, nickname: str) -> None:
        assert self._db is not None
        await self._db.execute(
            """INSERT INTO users (user_id, nickname, updated_at)
               VALUES (?, ?, unixepoch('subsec'))
               ON CONFLICT(user_id) DO UPDATE SET
                   nickname = excluded.nickname,
                   updated_at = excluded.updated_at""",
            (user_id, nickname),
        )
        await self._db.commit()

    async def get_user(self, user_id: str) -> dict | None:
        assert self._db is not None
        async with self._db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def get_all_users(self) -> list[dict]:
        assert self._db is not None
        async with self._db.execute("SELECT * FROM users ORDER BY updated_at DESC") as cur:
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def set_allowed(self, user_id: str, allowed: bool) -> None:
        assert self._db is not None
        await self._db.execute(
            "UPDATE users SET is_allowed = ?, updated_at = unixepoch('subsec') WHERE user_id = ?",
            (1 if allowed else 0, user_id),
        )
        await self._db.commit()

    async def is_allowed(self, user_id: str) -> bool:
        assert self._db is not None
        async with self._db.execute(
            "SELECT is_allowed FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        return bool(row["is_allowed"]) if row else False
