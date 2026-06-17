from __future__ import annotations

import logging
import stat
import textwrap
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from post_office.config import PrinterConfig
from post_office.models import Attachment, Message

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CpclLayout:
    page_width: int = 576
    text_char_width: int = 8
    bottom_margin: int = 32

    @property
    def max_image_height(self) -> int:
        return self.page_width // 2

    def image_width_for_chars(self, width_chars: int) -> int:
        return max(1, min(width_chars * self.text_char_width, self.page_width))


_CPCL_LAYOUT = _CpclLayout()


class ThermalPrinter:
    def __init__(self, config: PrinterConfig) -> None:
        self.config = config
        self._last_printed_date: date | None = None

    def print_message(self, message: Message) -> list[str]:
        prefix_lines = date_separator_lines(
            self._last_printed_date,
            message.timestamp.date(),
            width=self.config.width_chars,
        )
        receipt = [*prefix_lines, *format_receipt(message, width=self.config.width_chars)]
        printable_images = image_attachments(message)
        if not self.config.enabled:
            self._last_printed_date = message.timestamp.date()
            return receipt + format_image_placeholders(
                printable_images,
                width=self.config.width_chars,
            )
        print_cpcl(
            self.config.device_path,
            message,
            width=self.config.width_chars,
            prefix_lines=prefix_lines,
        )
        self._last_printed_date = message.timestamp.date()
        self._delete_printed_images(printable_images)
        return receipt

    def _delete_printed_images(self, attachments: tuple[Attachment, ...]) -> None:
        for attachment in attachments:
            if attachment.local_path is None:
                continue
            try:
                attachment.local_path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("failed to delete printed image %s: %s", attachment.local_path, exc)


def format_receipt(message: Message, *, width: int = 32) -> list[str]:
    source = message.source.value.upper()
    sender = message.sender_name or message.sender_id
    if message.is_group_chat:
        chat = message.chat_name or message.chat_id
        sender = f"{chat} > {sender}"
    body = message.text.strip() or _fallback_body(message)

    text = f"{message.timestamp:%H:%M} {source} {sender}: {body}"

    return textwrap.wrap(
        text,
        width=width,
        replace_whitespace=False,
        drop_whitespace=False,
    ) or [""]


def date_separator_lines(
    previous_date: date | None,
    current_date: date,
    *,
    width: int = 32,
) -> list[str]:
    if previous_date is None or previous_date == current_date:
        return []
    return ["", current_date.isoformat().center(width), ""]


def format_image_placeholders(
    attachments: tuple[Attachment, ...],
    *,
    width: int = 32,
) -> list[str]:
    lines: list[str] = []
    for attachment in attachments:
        if attachment.local_path is None:
            continue
        lines.extend(
            textwrap.wrap(
                f"[image: {attachment.local_path}]",
                width=width,
                replace_whitespace=False,
                drop_whitespace=False,
            )
        )
    return lines


def print_cpcl(
    device_path: Path,
    message: Message,
    *,
    width: int = 32,
    prefix_lines: list[str] | None = None,
) -> None:
    _ensure_printer_device(device_path)
    payload = format_cpcl(
        message,
        width=width,
        prefix_lines=prefix_lines,
    ).encode(
        "cp437",
        errors="replace",
    )
    with device_path.open("wb") as device:
        device.write(payload)
        device.flush()


def _ensure_printer_device(device_path: Path) -> None:
    if not device_path.exists():
        msg = f"printer device does not exist: {device_path}"
        raise RuntimeError(msg)
    if device_path.is_dir():
        msg = f"printer device path is a directory: {device_path}"
        raise RuntimeError(msg)
    if device_path.is_absolute() and device_path.parts[:2] == ("/", "dev"):
        mode = device_path.stat().st_mode
        if not stat.S_ISCHR(mode):
            msg = f"printer device is not a character device: {device_path}"
            raise RuntimeError(msg)


def format_cpcl(
    message: Message,
    *,
    width: int = 32,
    prefix_lines: list[str] | None = None,
) -> str:
    image_width = _cpcl_image_width_from_text_width(width)
    lines = [*(prefix_lines or []), *format_receipt(message, width=width)]
    images = [
        _cpcl_image_command(attachment.local_path, max_width=image_width)
        for attachment in image_attachments(message)
        if attachment.local_path is not None
    ]

    line_height = 16
    text_height = len(lines) * line_height
    image_gap = 12 if lines and images else 0
    image_height = sum(image.height for image in images)
    image_spacing = max(len(images) - 1, 0) * _CPCL_LAYOUT.bottom_margin
    height = (
        _CPCL_LAYOUT.bottom_margin
        + text_height
        + image_gap
        + image_height
        + image_spacing
    )

    commands = [
        f"! 0 200 200 {height} 1",
        f"PAGE-WIDTH {_CPCL_LAYOUT.page_width}",
        f"MULTILINE {line_height} TEXT 0 0 0 0",
    ]

    commands.extend(_cpcl_text(line) for line in lines)
    commands.append("ENDML")

    y = text_height + image_gap
    for image in images:
        commands.append(f"EG {image.width_bytes} {image.height} {image.x} {y} {image.data}")
        y += image.height + _CPCL_LAYOUT.bottom_margin
    commands.extend(["PRINT", ""])

    return "\r\n".join(commands)


def image_attachments(message: Message) -> tuple[Attachment, ...]:
    return tuple(
        attachment for attachment in message.attachments if _is_image_attachment(attachment)
    )


def _is_image_attachment(attachment: Attachment) -> bool:
    if attachment.local_path is None:
        return False
    if not attachment.local_path.exists():
        logger.warning("skipping missing image attachment: %s", attachment.local_path)
        return False
    if attachment.content_type and attachment.content_type.startswith("image/"):
        return True
    suffix = attachment.local_path.suffix.lower()
    if suffix in {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}:
        return True
    return _file_is_image(attachment.local_path)


def _fallback_body(message: Message) -> str:
    if image_attachments(message):
        return "[image]"
    if message.attachments:
        return "[attachment]"
    return "[non-text message]"


def _file_is_image(path: Path) -> bool:
    try:
        from PIL import Image
    except ImportError:
        return False

    try:
        with Image.open(path) as image:
            image.verify()
    except OSError:
        return False
    return True


class _CpclImage:
    def __init__(self, *, width_bytes: int, height: int, x: int, data: str) -> None:
        self.width_bytes = width_bytes
        self.height = height
        self.x = x
        self.data = data


def _cpcl_image_command(path: Path, *, max_width: int) -> _CpclImage:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        msg = "Pillow is required for CPCL image printing"
        raise RuntimeError(msg) from exc

    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("L")
        if image.height > image.width:
            image = image.rotate(90, expand=True)
        bounded_width = max(1, min(max_width, _CPCL_LAYOUT.page_width))
        scale = min(bounded_width / image.width, _CPCL_LAYOUT.max_image_height / image.height, 1)
        if scale < 1:
            size = (
                max(1, round(image.width * scale)),
                max(1, round(image.height * scale)),
            )
            image = image.resize(size)
        mono = image.convert("1")

    width, height = mono.size
    width_bytes = (width + 7) // 8
    data = _cpcl_hex_bitmap(mono, width_bytes=width_bytes)
    x = max((_CPCL_LAYOUT.page_width - width) // 2, 0)
    return _CpclImage(width_bytes=width_bytes, height=height, x=x, data=data)


def _cpcl_image_width_from_text_width(width: int) -> int:
    return _CPCL_LAYOUT.image_width_for_chars(width)


def _cpcl_hex_bitmap(image: Any, *, width_bytes: int) -> str:
    pixels = image.load()
    width, height = image.size
    rows: list[str] = []
    for y in range(height):
        row = bytearray(width_bytes)
        for x in range(width):
            if pixels[x, y] == 0:
                row[x // 8] |= 0x80 >> (x % 8)
        rows.append(row.hex().upper())
    return "".join(rows)


def _cpcl_text(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ")
