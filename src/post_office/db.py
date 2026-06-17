from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from post_office.models import Attachment, Message, Source

MESSAGES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    chat_name TEXT,
    is_group_chat INTEGER NOT NULL DEFAULT 0,
    sender_id TEXT NOT NULL,
    sender_name TEXT,
    source_message_id TEXT,
    timestamp TEXT NOT NULL,
    received_at TEXT NOT NULL,
    text TEXT NOT NULL,
    attachments_json TEXT NOT NULL,
    raw_json TEXT NOT NULL
)
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def migrate(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                f"""
                {MESSAGES_TABLE_SQL};

                CREATE TABLE IF NOT EXISTS delivery_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL REFERENCES messages(id),
                    target TEXT NOT NULL,
                    delivered_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    UNIQUE(message_id, target)
                );

                """
            )

    def insert_message(self, message: Message) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO messages (
                    id, dedupe_key, source, chat_id, chat_name, is_group_chat,
                    sender_id, sender_name, source_message_id, timestamp, received_at,
                    text, attachments_json, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _message_to_row(message),
            )
            return cursor.rowcount == 1

    def list_messages(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Message]:
        clauses: list[str] = []
        params: list[str] = []
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(_dt(start))
        if end is not None:
            clauses.append("timestamp < ?")
            params.append(_dt(end))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM messages {where} ORDER BY timestamp ASC"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_row_to_message(row) for row in rows]

    def undelivered_messages(self, target: str) -> list[Message]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT m.*
                FROM messages m
                LEFT JOIN delivery_log d ON d.message_id = m.id AND d.target = ?
                WHERE d.id IS NULL OR d.status = 'failed'
                ORDER BY m.timestamp ASC
                """,
                (target,),
            ).fetchall()
        return [_row_to_message(row) for row in rows]

    def record_delivery(
        self,
        message_id: str,
        target: str,
        status: str,
        error: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO delivery_log(message_id, target, delivered_at, status, error)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message_id, target, _dt(datetime.now(UTC)), status, error),
            )


def _message_to_row(message: Message) -> tuple[Any, ...]:
    attachments = [
        {
            **attachment.__dict__,
            "local_path": str(attachment.local_path) if attachment.local_path else None,
        }
        for attachment in message.attachments
    ]
    return (
        message.id,
        message.dedupe_key,
        message.source.value,
        message.chat_id,
        message.chat_name,
        int(message.is_group_chat),
        message.sender_id,
        message.sender_name,
        message.source_message_id,
        _dt(message.timestamp),
        _dt(message.received_at),
        message.text,
        json.dumps(attachments, sort_keys=True),
        json.dumps(message.raw, sort_keys=True, default=str),
    )


def _row_to_message(row: sqlite3.Row) -> Message:
    attachments = tuple(
        Attachment(
            **{
                **item,
                "local_path": Path(item["local_path"]) if item.get("local_path") else None,
            }
        )
        for item in json.loads(row["attachments_json"])
    )
    return Message(
        id=row["id"],
        source=Source(row["source"]),
        chat_id=row["chat_id"],
        chat_name=row["chat_name"],
        is_group_chat=bool(row["is_group_chat"]),
        sender_id=row["sender_id"],
        sender_name=row["sender_name"],
        source_message_id=row["source_message_id"],
        timestamp=_parse_dt(row["timestamp"]),
        received_at=_parse_dt(row["received_at"]),
        text=row["text"],
        attachments=attachments,
        raw=json.loads(row["raw_json"]),
    )


def _dt(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
