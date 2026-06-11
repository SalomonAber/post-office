from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from post_office.config import SignalConfig
from post_office.models import Message, Source


class SignalAdapter:
    def __init__(self, config: SignalConfig) -> None:
        self.config = config

    async def messages(self) -> AsyncIterator[Message]:
        msg = "Signal event loop is not implemented yet; use normalize_signal_event for fixtures"
        raise NotImplementedError(msg)
        yield


def normalize_signal_event(event: dict[str, Any], *, account: str) -> Message | None:
    envelope = event.get("envelope", event)
    sync_message = envelope.get("syncMessage", {})
    sent_message = sync_message.get("sentMessage", {})
    data_message = envelope.get("dataMessage") or sent_message.get("message")
    if not data_message:
        return None

    source = str(envelope.get("source") or envelope.get("sourceNumber") or account)
    chat_id = str(envelope.get("groupInfo", {}).get("groupId") or source)
    timestamp_ms = int(data_message.get("timestamp") or envelope.get("timestamp") or 0)
    text = str(data_message.get("message") or "")
    source_message_id = str(
        data_message.get("timestamp") or envelope.get("timestamp") or ""
    ) or None
    if timestamp_ms:
        timestamp = datetime.fromtimestamp(timestamp_ms / 1000, UTC)
    else:
        timestamp = datetime.now(UTC)

    return Message(
        source=Source.SIGNAL,
        source_account_id=account,
        chat_id=chat_id,
        sender_id=source,
        sender_name=source,
        source_message_id=source_message_id,
        timestamp=timestamp,
        text=text,
        raw=event,
    )
