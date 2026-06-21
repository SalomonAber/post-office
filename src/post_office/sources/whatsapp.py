from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from post_office.config import WhatsAppConfig
from post_office.models import Message, Source
from post_office.sources.base import normalize_attachments, render_terminal_qr

logger = logging.getLogger(__name__)
WHATSAPP_BRIDGE_PATH_ENV = "POST_OFFICE_WHATSAPP_BRIDGE_PATH"
WHATSAPP_BRIDGE_COMMAND = (
    "node",
    os.environ.get(WHATSAPP_BRIDGE_PATH_ENV, "bridges/whatsapp/index.js"),
)


class WhatsAppAdapter:
    def __init__(self, config: WhatsAppConfig) -> None:
        self.config = config

    def check(self) -> tuple[str, ...]:
        command = WHATSAPP_BRIDGE_COMMAND
        if not command:
            return ("WhatsApp bridge command is empty.",)
        executable = command[0]
        if os.sep in executable:
            if not os.path.exists(executable):
                return (f"WhatsApp bridge executable does not exist: {executable}",)
            return ()
        if shutil.which(executable) is None:
            return (f"WhatsApp bridge executable was not found on PATH: {executable}",)
        return ()

    async def messages(self) -> AsyncIterator[Message]:
        consecutive_failures = 0
        while True:
            process = await self._start_bridge()
            if process.stdout is None or process.stderr is None:
                msg = "WhatsApp bridge stdout/stderr was not captured"
                raise RuntimeError(msg)

            stderr_task = asyncio.create_task(_log_stderr(process.stderr))
            messages = 0
            try:
                async for raw_line in process.stdout:
                    line = raw_line.decode(errors="replace").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("ignored invalid WhatsApp bridge JSON line")
                        continue
                    message = normalize_baileys_event(
                        event,
                        ignore_muted_chats=self.config.ignore_muted_chats,
                    )
                    if message is not None:
                        messages += 1
                        yield message
                    else:
                        log_bridge_event(event)
            finally:
                await process.wait()
                stderr_task.cancel()
                await asyncio.gather(stderr_task, return_exceptions=True)

            if process.returncode == 0:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
            retry_after = whatsapp_retry_delay(self.config, consecutive_failures)
            logger.warning(
                "WhatsApp bridge exited exit_code=%s messages=%s retry_after=%ss",
                process.returncode,
                messages,
                retry_after,
            )
            await asyncio.sleep(retry_after)

    async def _start_bridge(self) -> asyncio.subprocess.Process:
        env = self._bridge_env()
        logger.info("starting WhatsApp bridge: %s", " ".join(WHATSAPP_BRIDGE_COMMAND))
        return await asyncio.create_subprocess_exec(
            *WHATSAPP_BRIDGE_COMMAND,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

    def _bridge_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["POST_OFFICE_WHATSAPP_AUTH_DIR"] = str(self.config.auth_dir)
        env["POST_OFFICE_WHATSAPP_MEDIA_DIR"] = str(self.config.media_dir)
        if self.config.include_own_messages:
            env["POST_OFFICE_WHATSAPP_INCLUDE_OWN_MESSAGES"] = "1"
        if self.config.ignore_muted_chats:
            env["POST_OFFICE_WHATSAPP_IGNORE_MUTED_CHATS"] = "1"
        return env


async def _log_stderr(stderr: asyncio.StreamReader) -> None:
    async for raw_line in stderr:
        line = raw_line.decode(errors="replace").strip()
        if line:
            logger.warning("WhatsApp bridge stderr: %s", line)


def whatsapp_retry_delay(config: WhatsAppConfig, consecutive_failures: int) -> int:
    base_delay = max(config.restart_delay_seconds, 1)
    max_delay = max(config.max_restart_delay_seconds, base_delay)
    multiplier = 2 ** max(consecutive_failures - 1, 0)
    return int(min(base_delay * multiplier, max_delay))


def log_bridge_event(event: dict[str, Any]) -> None:
    event_type = event.get("type")
    if event_type == "qr":
        terminal_qr = event.get("terminal")
        raw_qr = event.get("qr")
        logger.info("WhatsApp bridge is waiting for QR pairing")
        if not isinstance(terminal_qr, str) or not terminal_qr:
            terminal_qr = render_terminal_qr(raw_qr) if isinstance(raw_qr, str) else None
        print("Scan this WhatsApp QR code from your phone:", file=sys.stderr, flush=True)
        print(terminal_qr or raw_qr or "QR payload missing", file=sys.stderr, flush=True)
        return
    if event_type == "ready":
        logger.info("WhatsApp bridge is ready")
        return
    if event_type == "closed":
        logger.warning(
            "WhatsApp bridge connection closed status=%s reason=%s message=%s",
            event.get("statusCode", "unknown"),
            event.get("reason", "unknown"),
            event.get("message", "unknown"),
        )
        return
    logger.info("ignored WhatsApp bridge event type=%s", event_type)


def normalize_baileys_event(
    event: dict[str, Any],
    *,
    ignore_muted_chats: bool = False,
) -> Message | None:
    if event.get("type") not in {None, "message"}:
        return None
    if ignore_muted_chats and _chat_is_muted(event):
        return None
    key = event.get("key", {})
    if not isinstance(key, dict):
        key = {}
    message = event.get("message", {})
    if not isinstance(message, dict):
        return None
    remote_jid = str(event.get("chatId") or key.get("remoteJid") or "")
    is_group_chat = remote_jid.endswith("@g.us")
    sender_id = str(event.get("senderId") or key.get("participant") or remote_jid)
    text = _extract_text(message)
    timestamp = _timestamp_seconds(event.get("messageTimestamp") or event.get("timestamp"))
    source_message_id = str(key.get("id") or event.get("id") or "") or None

    if not remote_jid:
        return None

    return Message(
        source=Source.WHATSAPP,
        chat_id=remote_jid,
        chat_name=(event.get("chatName") if is_group_chat else None),
        is_group_chat=is_group_chat,
        sender_id=sender_id,
        sender_name=event.get("senderName") or event.get("pushName"),
        source_message_id=source_message_id,
        timestamp=datetime.fromtimestamp(timestamp, UTC) if timestamp else datetime.now(UTC),
        text=text,
        attachments=normalize_attachments(event.get("attachments")),
        raw=event,
    )


def _extract_text(message: dict[str, Any]) -> str:
    unwrapped = _unwrap_message(message)
    return str(
        unwrapped.get("conversation")
        or unwrapped.get("extendedTextMessage", {}).get("text")
        or unwrapped.get("imageMessage", {}).get("caption")
        or unwrapped.get("videoMessage", {}).get("caption")
        or unwrapped.get("documentMessage", {}).get("caption")
        or unwrapped.get("buttonsResponseMessage", {}).get("selectedDisplayText")
        or unwrapped.get("listResponseMessage", {}).get("title")
        or ""
    )


def _unwrap_message(message: dict[str, Any]) -> dict[str, Any]:
    current = message
    for key in ("ephemeralMessage", "viewOnceMessage", "viewOnceMessageV2"):
        nested = current.get(key)
        if isinstance(nested, dict) and isinstance(nested.get("message"), dict):
            current = nested["message"]
    return current


def _timestamp_seconds(value: object) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        return int(float(value))
    if isinstance(value, dict):
        low = int(value.get("low") or 0)
        high = int(value.get("high") or 0)
        unsigned = bool(value.get("unsigned", False))
        timestamp = (high << 32) + low
        if not unsigned and high < 0:
            timestamp -= 1 << 64
        return timestamp
    return 0


def _chat_is_muted(event: dict[str, Any]) -> bool:
    if event.get("chatMuted") is True:
        return True
    chat = event.get("chat")
    return isinstance(chat, dict) and _timestamp_seconds(chat.get("muteEndTime")) > 0
