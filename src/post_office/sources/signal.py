from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import shutil
import sqlite3
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
SIGNAL_MUTED_UNTIL_FIELD_NUMBER = 6


class SignalAdapter:
    def __init__(self, config: SignalConfig) -> None:
        self.config = config
        self.mute_store = SignalMuteStore(config.data_dir)

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

            if signal_data_dir_is_linked(self.config):
                logger.info("Signal linked even though signal-cli exited with code %s", exit_code)
                return

            error = summarize_signal_cli_error(stderr)
            if signal_link_error_is_retryable(error):
                retry_after = self.config.restart_delay_seconds
                logger.info(
                    "Signal link attempt did not finish cleanly (%s); "
                    "printing a new QR code in %ss",
                    error,
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
                    if self.config.ignore_muted_chats and self.mute_store.event_is_muted(event):
                        logger.info(
                            "ignored muted Signal event kind=%s summary=%s",
                            signal_event_kind(event),
                            signal_event_summary(event),
                        )
                        continue

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


class SignalMuteStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def event_is_muted(self, event: dict[str, Any]) -> bool:
        reference = signal_chat_reference(event)
        if reference is None:
            return False
        chat_id, is_group_chat = reference
        return self.chat_is_muted(chat_id, is_group_chat=is_group_chat)

    def chat_is_muted(self, chat_id: str, *, is_group_chat: bool) -> bool:
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        for database_path in signal_account_database_paths(self.data_dir):
            try:
                mute_until = _read_signal_chat_mute_until(
                    database_path,
                    chat_id,
                    is_group_chat=is_group_chat,
                )
            except sqlite3.Error as error:
                logger.debug("failed to read Signal mute state from %s: %s", database_path, error)
                continue
            if mute_until > now_ms:
                return True
        return False


def signal_account_database_paths(data_dir: Path) -> tuple[Path, ...]:
    account_data_dir = data_dir / "data"
    if not account_data_dir.is_dir():
        return ()
    return tuple(sorted(account_data_dir.glob("*.d/account.db")))


def signal_chat_reference(event: dict[str, Any]) -> tuple[str, bool] | None:
    envelope = event.get("envelope", event)
    if not isinstance(envelope, dict):
        return None

    data_message = _extract_data_message(envelope)
    if not isinstance(data_message, dict) or not data_message:
        return None

    source = str(envelope.get("source") or envelope.get("sourceNumber") or "unknown")
    group_info = data_message.get("groupInfo") or envelope.get("groupInfo") or {}
    if not isinstance(group_info, dict):
        group_info = {}
    group_id = group_info.get("groupId")
    if group_id:
        return str(group_id), True

    destination = data_message.get("destination") or data_message.get("destinationNumber")
    return str(destination or source), False


def _read_signal_chat_mute_until(
    database_path: Path,
    chat_id: str,
    *,
    is_group_chat: bool,
) -> int:
    uri = f"file:{database_path}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=1) as connection:
        if is_group_chat:
            return _read_signal_group_mute_until(connection, chat_id)
        return _read_signal_recipient_mute_until(connection, chat_id)


def _read_signal_recipient_mute_until(connection: sqlite3.Connection, chat_id: str) -> int:
    cursor = connection.execute(
        """
        SELECT mute_until
        FROM recipient
        WHERE number = ? OR aci = ? OR pni = ? OR username = ?
        LIMIT 1
        """,
        (chat_id, chat_id, chat_id, chat_id),
    )
    row = cursor.fetchone()
    return int(row[0]) if row is not None and row[0] is not None else 0


def _read_signal_group_mute_until(connection: sqlite3.Connection, chat_id: str) -> int:
    group_id = _decode_signal_group_id(chat_id)
    if group_id is None:
        return 0

    for table in ("group_v1", "group_v2"):
        cursor = connection.execute(
            f"SELECT storage_record FROM {table} WHERE group_id = ? LIMIT 1",
            (group_id,),
        )
        row = cursor.fetchone()
        if row is None or row[0] is None:
            continue
        mute_until = _protobuf_uint64_field(row[0], SIGNAL_MUTED_UNTIL_FIELD_NUMBER)
        if mute_until:
            return mute_until
    return 0


def _decode_signal_group_id(chat_id: str) -> bytes | None:
    import base64
    import binascii

    normalized = chat_id.strip()
    padding = "=" * (-len(normalized) % 4)
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            return decoder(normalized + padding)
        except (binascii.Error, ValueError):
            continue
    return None


def _protobuf_uint64_field(payload: bytes, field_number: int) -> int:
    index = 0
    while index < len(payload):
        key, index = _read_protobuf_varint(payload, index)
        wire_type = key & 0b111
        current_field_number = key >> 3
        if wire_type == 0:
            value, index = _read_protobuf_varint(payload, index)
            if current_field_number == field_number:
                return value
            continue
        if wire_type == 1:
            index += 8
        elif wire_type == 2:
            length, index = _read_protobuf_varint(payload, index)
            index += length
        elif wire_type == 5:
            index += 4
        else:
            return 0
    return 0


def _read_protobuf_varint(payload: bytes, index: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while index < len(payload):
        byte = payload[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, index
        shift += 7
        if shift >= 64:
            break
    return 0, len(payload)


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
        if (
            line.startswith("error:")
            or ": error:" in line
            or line.startswith("Failed ")
            or line.startswith("free():")
        ):
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
    return (
        "link request error: connection closed" in normalized
        or "free(): invalid size" in normalized
    )


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
