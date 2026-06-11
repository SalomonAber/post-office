from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from post_office.config import SignalConfig
from post_office.models import Message, Source

logger = logging.getLogger(__name__)


class SignalAdapter:
    def __init__(self, config: SignalConfig) -> None:
        self.config = config

    async def messages(self) -> AsyncIterator[Message]:
        while True:
            command = signal_receive_command(self.config)
            logger.info("starting signal-cli receive: %s", " ".join(command))
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            if process.stdout is None or process.stderr is None:
                msg = "signal-cli stdout/stderr was not captured"
                raise RuntimeError(msg)

            stdout, stderr_bytes = await process.communicate()
            stderr = stderr_bytes.decode(errors="replace").strip()
            exit_code = process.returncode
            if exit_code != 0:
                msg = f"signal-cli receive failed with exit code {exit_code}: {stderr}"
                raise RuntimeError(msg)

            output = stdout.decode(errors="replace")
            events = parse_signal_json_output(output)
            messages: list[Message] = []
            ignored: dict[str, int] = {}
            for event in events:
                message = normalize_signal_event(event, account=self.config.account)
                if message is not None:
                    messages.append(message)
                else:
                    kind = signal_event_kind(event)
                    ignored[kind] = ignored.get(kind, 0) + 1
            logger.info(
                "signal-cli receive completed events=%s messages=%s ignored=%s",
                len(events),
                len(messages),
                ignored,
            )
            for message in messages:
                yield message
            await asyncio.sleep(self.config.restart_delay_seconds)


def signal_receive_command(config: SignalConfig) -> tuple[str, ...]:
    return (
        config.signal_cli,
        "-a",
        config.account,
        "-o",
        "json",
        "receive",
        "--timeout",
        str(config.receive_timeout_seconds),
    )


def signal_list_accounts_command(config: SignalConfig) -> tuple[str, ...]:
    return (config.signal_cli, "listAccounts")


def signal_account_is_registered(config: SignalConfig) -> bool:
    completed = subprocess.run(
        signal_list_accounts_command(config),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return False
    return config.account in parse_signal_accounts(completed.stdout)


def parse_signal_accounts(output: str) -> tuple[str, ...]:
    accounts: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Number:"):
            accounts.append(stripped.removeprefix("Number:").strip())
    return tuple(accounts)


def parse_signal_json_line(line: str) -> tuple[dict[str, Any], ...]:
    return parse_signal_json_output(line)


def parse_signal_json_output(output: str) -> tuple[dict[str, Any], ...]:
    stripped = output.strip()
    if not stripped:
        return ()
    decoder = json.JSONDecoder()
    index = 0
    events: list[dict[str, Any]] = []
    while index < len(stripped):
        payload, index = decoder.raw_decode(stripped, index)
        events.extend(_parse_signal_payload(payload))
        while index < len(stripped) and stripped[index].isspace():
            index += 1
    return tuple(events)


def _parse_signal_payload(payload: object) -> tuple[dict[str, Any], ...]:
    if isinstance(payload, list):
        return tuple(item for item in payload if isinstance(item, dict))
    if isinstance(payload, dict):
        return (payload,)
    return ()


def normalize_signal_event(event: dict[str, Any], *, account: str) -> Message | None:
    envelope = event.get("envelope", event)
    sync_message = envelope.get("syncMessage", {})
    sent_message = sync_message.get("sentMessage", {})
    data_message = envelope.get("dataMessage") or sent_message
    if not isinstance(data_message, dict) or not data_message:
        return None

    source = str(envelope.get("source") or envelope.get("sourceNumber") or account)
    group_info = data_message.get("groupInfo") or envelope.get("groupInfo") or {}
    destination = sent_message.get("destination") or sent_message.get("destinationNumber")
    chat_id = str(group_info.get("groupId") or destination or source)
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


def signal_event_kind(event: dict[str, Any]) -> str:
    envelope = event.get("envelope", event)
    for key in (
        "dataMessage",
        "syncMessage",
        "receiptMessage",
        "typingMessage",
        "callMessage",
        "decryptionErrorMessage",
    ):
        if key in envelope:
            if key == "syncMessage" and isinstance(envelope[key], dict):
                sync_message = envelope[key]
                for sync_key in ("sentMessage", "readMessages", "viewOnceOpen"):
                    if sync_key in sync_message:
                        return f"syncMessage.{sync_key}"
            return key
    return "unknown"
