from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import shutil
import subprocess
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from post_office.config import SignalConfig
from post_office.models import Attachment, Message, Source
from post_office.sources.base import normalize_attachments, render_terminal_qr

logger = logging.getLogger(__name__)
SIGNAL_CLI = "signal-cli"
SIGNAL_LINKED_DEVICE_NAME = "post-office"
SIGNAL_RECEIVE_TIMEOUT_SECONDS = -1


class SignalAdapter:
    def __init__(self, config: SignalConfig) -> None:
        self.config = config

    async def prepare(self) -> None:
        while not signal_data_dir_is_linked(self.config):
            command = signal_link_command(self.config)
            logger.info("starting signal-cli link: %s", " ".join(command))
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=signal_cli_env(self.config),
            )
            if process.stdout is None or process.stderr is None:
                msg = "signal-cli link stdout/stderr was not captured"
                raise RuntimeError(msg)

            async for raw_line in process.stdout:
                line = raw_line.decode(errors="replace").strip()
                if not line:
                    continue
                print("Scan this Signal QR code from your phone:", flush=True)
                print(render_terminal_qr(line) or line, flush=True)

            stderr = (await process.stderr.read()).decode(errors="replace").strip()
            exit_code = await process.wait()
            if exit_code == 0:
                continue

            error = summarize_signal_cli_error(stderr)
            if signal_link_error_is_retryable(error):
                retry_after = self.config.restart_delay_seconds
                logger.info(
                    "Signal link QR was not scanned before the session closed; "
                    "printing a new QR code in %ss",
                    retry_after,
                )
                await asyncio.sleep(retry_after)
                continue

            msg = f"signal-cli link failed: {error}"
            raise RuntimeError(msg)

    async def messages(self) -> AsyncIterator[Message]:
        consecutive_failures = 0
        while True:
            command = signal_receive_command(self.config)
            logger.info("starting signal-cli receive: %s", " ".join(command))
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=signal_cli_env(self.config),
            )
            if process.stdout is None or process.stderr is None:
                msg = "signal-cli stdout/stderr was not captured"
                raise RuntimeError(msg)

            stderr_task = asyncio.create_task(process.stderr.read())
            try:
                async for event in iter_signal_json_events(process.stdout):
                    message = normalize_signal_event(
                        event,
                        media_dir=self.config.media_dir,
                        include_own_messages=self.config.include_own_messages,
                    )
                    if message is not None:
                        consecutive_failures = 0
                        yield message
                    else:
                        logger.info(
                            "ignored Signal event kind=%s summary=%s",
                            signal_event_kind(event),
                            signal_event_summary(event),
                        )
            finally:
                await process.wait()

            stderr = (await stderr_task).decode(errors="replace").strip()
            if process.returncode != 0:
                consecutive_failures += 1
                retry_after = signal_retry_delay(self.config, consecutive_failures)
                logger.warning(
                    "signal-cli receive failed exit_code=%s attempt=%s retry_after=%ss error=%s",
                    process.returncode,
                    consecutive_failures,
                    retry_after,
                    summarize_signal_cli_error(stderr),
                )
                await asyncio.sleep(retry_after)
                continue

            await asyncio.sleep(self.config.restart_delay_seconds)


def signal_receive_command(config: SignalConfig) -> tuple[str, ...]:
    return (
        SIGNAL_CLI,
        *signal_data_dir_args(config),
        "-o",
        "json",
        "receive",
        "--timeout",
        str(SIGNAL_RECEIVE_TIMEOUT_SECONDS),
    )


def signal_link_command(config: SignalConfig) -> tuple[str, ...]:
    return (
        SIGNAL_CLI,
        *signal_data_dir_args(config),
        "link",
        "-n",
        SIGNAL_LINKED_DEVICE_NAME,
    )


def signal_list_linked_numbers_command(config: SignalConfig) -> tuple[str, ...]:
    return (SIGNAL_CLI, *signal_data_dir_args(config), "listAccounts")


def signal_data_dir_args(config: SignalConfig) -> tuple[str, ...]:
    if config.data_dir.name == "signal-cli":
        return ()
    return ("-d", str(config.data_dir))


def signal_cli_env(config: SignalConfig) -> dict[str, str]:
    env = os.environ.copy()
    if config.data_dir.name == "signal-cli":
        env["XDG_DATA_HOME"] = str(config.data_dir.parent)
    return env


def signal_retry_delay(config: SignalConfig, consecutive_failures: int) -> int:
    base_delay = max(config.restart_delay_seconds, 1)
    max_delay = max(config.max_restart_delay_seconds, base_delay)
    multiplier = 2 ** max(consecutive_failures - 1, 0)
    return int(min(base_delay * multiplier, max_delay))


def summarize_signal_cli_error(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return "no stderr"
    for line in reversed(lines):
        if line.startswith("error:") or ": error:" in line or line.startswith("Failed "):
            return line
    first_line = lines[0]
    if first_line.startswith("java.lang.NullPointerException"):
        for line in lines[1:]:
            if "ReceiveHelper.retryFailedReceivedMessage" in line:
                return f"{first_line} while retrying cached failed Signal messages"
        return first_line
    return " | ".join(lines[-3:])


def signal_link_error_is_retryable(error: str) -> bool:
    normalized = error.casefold()
    return "link request error: connection closed" in normalized


def signal_data_dir_is_linked(config: SignalConfig) -> bool:
    completed = subprocess.run(
        signal_list_linked_numbers_command(config),
        check=False,
        capture_output=True,
        text=True,
        env=signal_cli_env(config),
    )
    if completed.returncode != 0:
        return False
    return bool(parse_signal_linked_numbers(completed.stdout))


def parse_signal_linked_numbers(output: str) -> tuple[str, ...]:
    numbers: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Number:"):
            numbers.append(stripped.removeprefix("Number:").strip())
    return tuple(numbers)


def parse_signal_json_line(line: str) -> tuple[dict[str, Any], ...]:
    return parse_signal_json_output(line)


async def iter_signal_json_events(
    stdout: asyncio.StreamReader,
) -> AsyncIterator[dict[str, Any]]:
    buffer = ""
    async for raw_line in stdout:
        buffer += raw_line.decode(errors="replace")
        events, buffer = parse_signal_json_prefix(buffer)
        for event in events:
            yield event
    events, _buffer = parse_signal_json_prefix(buffer)
    for event in events:
        yield event


def parse_signal_json_prefix(output: str) -> tuple[tuple[dict[str, Any], ...], str]:
    stripped = output.lstrip()
    decoder = json.JSONDecoder()
    index = 0
    events: list[dict[str, Any]] = []
    while index < len(stripped):
        try:
            payload, index = decoder.raw_decode(stripped, index)
        except json.JSONDecodeError:
            return tuple(events), stripped[index:]
        events.extend(_parse_signal_payload(payload))
        while index < len(stripped) and stripped[index].isspace():
            index += 1
    return tuple(events), ""


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


def normalize_signal_event(
    event: dict[str, Any],
    *,
    media_dir: Path | None = None,
    include_own_messages: bool = False,
) -> Message | None:
    envelope = event.get("envelope", event)
    if not isinstance(envelope, dict):
        return None

    if not include_own_messages and _is_sync_sent_message(envelope):
        return None

    data_message = _extract_data_message(envelope)
    if not isinstance(data_message, dict) or not data_message:
        return None

    source = str(envelope.get("source") or envelope.get("sourceNumber") or "unknown")
    group_info = data_message.get("groupInfo") or envelope.get("groupInfo") or {}
    if not isinstance(group_info, dict):
        group_info = {}
    destination = data_message.get("destination") or data_message.get("destinationNumber")
    chat_id = str(group_info.get("groupId") or destination or source)
    is_group_chat = bool(group_info.get("groupId"))
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
        chat_id=chat_id,
        chat_name=group_info.get("groupName") or group_info.get("name"),
        is_group_chat=is_group_chat,
        sender_id=source,
        sender_name=source,
        source_message_id=source_message_id,
        timestamp=timestamp,
        text=text,
        attachments=normalize_signal_attachments(
            data_message.get("attachments"),
            media_dir=media_dir,
            chat_id=chat_id,
            source_message_id=source_message_id,
        ),
        raw=event,
    )


def _is_sync_sent_message(envelope: dict[str, Any]) -> bool:
    sync_message = envelope.get("syncMessage")
    return isinstance(sync_message, dict) and isinstance(sync_message.get("sentMessage"), dict)


def normalize_signal_attachments(
    value: object,
    *,
    media_dir: Path | None = None,
    chat_id: str = "unknown",
    source_message_id: str | None = None,
) -> tuple[Attachment, ...]:
    attachments = normalize_attachments(value)
    if media_dir is None:
        return attachments
    return tuple(
        _copy_signal_attachment(
            attachment,
            media_dir=media_dir,
            chat_id=chat_id,
            source_message_id=source_message_id,
            index=index,
        )
        for index, attachment in enumerate(attachments)
    )


def _copy_signal_attachment(
    attachment: Attachment,
    *,
    media_dir: Path,
    chat_id: str,
    source_message_id: str | None,
    index: int,
) -> Attachment:
    if attachment.local_path is None or not attachment.local_path.exists():
        return attachment

    directory = media_dir / _safe_path_part(chat_id) / _safe_path_part(
        source_message_id or attachment.source_id or "synthetic"
    )
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / _signal_attachment_filename(attachment, index=index)
    if attachment.local_path.resolve() != destination.resolve():
        shutil.copy2(attachment.local_path, destination)

    return Attachment(
        content_type=attachment.content_type or mimetypes.guess_type(destination)[0],
        filename=attachment.filename or destination.name,
        local_path=destination,
        size_bytes=attachment.size_bytes or destination.stat().st_size,
        source_id=attachment.source_id,
    )


def _signal_attachment_filename(attachment: Attachment, *, index: int) -> str:
    name = attachment.filename
    if not name and attachment.local_path is not None:
        name = attachment.local_path.name
    if not name:
        name = attachment.source_id or f"attachment-{index}"
    safe_name = _safe_path_part(name)
    if Path(safe_name).suffix:
        return safe_name
    extension = mimetypes.guess_extension(attachment.content_type or "") or ""
    return f"{safe_name}{extension}"


def _safe_path_part(value: str) -> str:
    safe = "".join(
        character if character.isalnum() or character in "._-" else "_" for character in value
    )
    return safe.strip("._") or "unknown"


def _extract_data_message(envelope: dict[str, Any]) -> dict[str, Any] | None:
    data_message = envelope.get("dataMessage")
    if isinstance(data_message, dict):
        return data_message

    edit_message = envelope.get("editMessage")
    if isinstance(edit_message, dict):
        data_message = edit_message.get("dataMessage")
        if isinstance(data_message, dict):
            return data_message

    sync_message = envelope.get("syncMessage")
    if isinstance(sync_message, dict):
        sent_message = sync_message.get("sentMessage")
        if isinstance(sent_message, dict):
            nested_data_message = sent_message.get("dataMessage")
            if isinstance(nested_data_message, dict):
                return {
                    **nested_data_message,
                    "destination": sent_message.get("destination"),
                    "destinationNumber": sent_message.get("destinationNumber"),
                }
            return sent_message
    return None


def signal_event_kind(event: dict[str, Any]) -> str:
    if "exception" in event:
        exception = event.get("exception")
        if isinstance(exception, dict) and isinstance(exception.get("type"), str):
            return f"exception.{exception['type']}"
        return "exception"

    envelope = event.get("envelope", event)
    if not isinstance(envelope, dict):
        return "unknown"
    for key in (
        "dataMessage",
        "editMessage",
        "syncMessage",
        "storyMessage",
        "receiptMessage",
        "typingMessage",
        "callMessage",
        "decryptionErrorMessage",
    ):
        if key in envelope:
            if key == "syncMessage" and isinstance(envelope[key], dict):
                sync_message = envelope[key]
                for sync_key in (
                    "sentMessage",
                    "sentStoryMessage",
                    "readMessages",
                    "viewOnceOpen",
                    "type",
                ):
                    if sync_key in sync_message:
                        return f"syncMessage.{sync_key}"
            return key
    return "unknown"


def signal_event_summary(event: dict[str, Any]) -> str:
    envelope = event.get("envelope")
    parts = [f"top={_sorted_keys(event)}"]
    if isinstance(envelope, dict):
        parts.append(f"envelope={_sorted_keys(envelope)}")
        sync_message = envelope.get("syncMessage")
        data_message = envelope.get("dataMessage")
    else:
        sync_message = event.get("syncMessage")
        data_message = event.get("dataMessage")
    if isinstance(sync_message, dict):
        parts.append(f"syncMessage={_sorted_keys(sync_message)}")
    if isinstance(data_message, dict):
        parts.append(f"dataMessage={_sorted_keys(data_message)}")
    return " ".join(parts)


def _sorted_keys(value: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(str(key) for key in value))
