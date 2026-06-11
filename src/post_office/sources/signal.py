from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from post_office.config import SignalConfig
from post_office.models import Message, Source


class SignalAdapter:
    def __init__(self, config: SignalConfig) -> None:
        self.config = config

    async def messages(self) -> AsyncIterator[Message]:
        while True:
            process = await asyncio.create_subprocess_exec(
                *signal_receive_command(self.config),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            if process.stdout is None:
                msg = "signal-cli stdout was not captured"
                raise RuntimeError(msg)

            async for raw_line in process.stdout:
                line = raw_line.decode().strip()
                if not line:
                    continue
                for event in parse_signal_json_line(line):
                    message = normalize_signal_event(event, account=self.config.account)
                    if message is not None:
                        yield message

            stderr = await _read_stderr(process)
            exit_code = await process.wait()
            if exit_code != 0:
                msg = f"signal-cli receive failed with exit code {exit_code}: {stderr}"
                raise RuntimeError(msg)
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
    return config.account in completed.stdout.splitlines()


def parse_signal_json_line(line: str) -> tuple[dict[str, Any], ...]:
    payload = json.loads(line)
    if isinstance(payload, list):
        return tuple(item for item in payload if isinstance(item, dict))
    if isinstance(payload, dict):
        return (payload,)
    return ()


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


async def _read_stderr(process: asyncio.subprocess.Process) -> str:
    if process.stderr is None:
        return ""
    return (await process.stderr.read()).decode(errors="replace").strip()
