from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from post_office.config import WhatsAppConfig
from post_office.models import Message, Source


class WhatsAppBridgeAdapter:
    def __init__(self, config: WhatsAppConfig, *, account_id: str = "default") -> None:
        self.config = config
        self.account_id = account_id

    async def messages(self) -> AsyncIterator[Message]:
        process = await asyncio.create_subprocess_exec(
            *self.config.bridge_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if process.stdout is None:
            msg = "WhatsApp bridge stdout was not captured"
            raise RuntimeError(msg)
        async for raw_line in process.stdout:
            line = raw_line.decode().strip()
            if not line:
                continue
            event = json.loads(line)
            message = normalize_baileys_event(event, account_id=self.account_id)
            if message is not None:
                yield message


def normalize_baileys_event(event: dict[str, Any], *, account_id: str) -> Message | None:
    if event.get("type") not in {None, "message"}:
        return None
    key = event.get("key", {})
    message = event.get("message", {})
    remote_jid = str(event.get("chatId") or key.get("remoteJid") or "")
    sender_id = str(event.get("senderId") or key.get("participant") or remote_jid)
    text = _extract_text(message)
    timestamp = int(event.get("messageTimestamp") or event.get("timestamp") or 0)
    source_message_id = str(key.get("id") or event.get("id") or "") or None

    if not remote_jid:
        return None

    return Message(
        source=Source.WHATSAPP,
        source_account_id=account_id,
        chat_id=remote_jid,
        chat_name=event.get("pushName"),
        sender_id=sender_id,
        sender_name=event.get("senderName") or event.get("pushName"),
        source_message_id=source_message_id,
        timestamp=datetime.fromtimestamp(timestamp, UTC) if timestamp else datetime.now(UTC),
        text=text,
        raw=event,
    )


def _extract_text(message: dict[str, Any]) -> str:
    return str(
        message.get("conversation")
        or message.get("extendedTextMessage", {}).get("text")
        or message.get("imageMessage", {}).get("caption")
        or message.get("videoMessage", {}).get("caption")
        or ""
    )
