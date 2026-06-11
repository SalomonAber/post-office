from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from post_office.config import InstagramConfig
from post_office.models import Message, Source


class InstagramAdapter:
    def __init__(self, config: InstagramConfig) -> None:
        self.config = config

    async def messages(self) -> AsyncIterator[Message]:
        msg = "Instagram polling loop is not implemented yet"
        raise NotImplementedError(msg)
        yield


def normalize_instagram_item(
    item: dict[str, Any],
    *,
    account_id: str,
    thread_id: str,
    thread_title: str | None = None,
) -> Message | None:
    text = str(item.get("text") or "")
    item_id = str(item.get("id") or item.get("item_id") or "")
    sender_id = str(item.get("user_id") or item.get("sender_id") or "")
    timestamp_value = item.get("timestamp") or item.get("timestamp_ms") or 0
    if not item_id or not sender_id:
        return None

    timestamp = _parse_timestamp(timestamp_value)
    return Message(
        source=Source.INSTAGRAM,
        source_account_id=account_id,
        chat_id=thread_id,
        chat_name=thread_title,
        sender_id=sender_id,
        source_message_id=item_id,
        timestamp=timestamp,
        text=text,
        raw=item,
    )


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    number = int(value or 0)
    if number > 10_000_000_000:
        number //= 1000
    return datetime.fromtimestamp(number, UTC) if number else datetime.now(UTC)
