from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from post_office.models import Attachment, Message


class SourceAdapter(Protocol):
    def messages(self) -> AsyncIterator[Message]:
        """Yield normalized messages from the source."""
        ...


@runtime_checkable
class CheckableSourceAdapter(SourceAdapter, Protocol):
    def check(self) -> tuple[str, ...]:
        """Return human-readable setup errors before the daemon starts."""
        ...


@runtime_checkable
class PreparableSourceAdapter(SourceAdapter, Protocol):
    async def prepare(self) -> None:
        """Run interactive source setup before live ingestion starts."""
        ...


def render_terminal_qr(payload: str) -> str | None:
    try:
        import pyqrcode  # type: ignore[import-untyped]
    except ImportError:
        return None

    code = pyqrcode.create(payload, error="M")
    return render_qr_matrix(code.code, quiet_zone=1)


def render_qr_matrix(matrix: list[list[int]], *, quiet_zone: int = 1) -> str:
    width = len(matrix[0]) if matrix else 0
    white_row = [0] * (width + quiet_zone * 2)
    padded = (
        [white_row.copy() for _ in range(quiet_zone)]
        + [[0] * quiet_zone + row + [0] * quiet_zone for row in matrix]
        + [white_row.copy() for _ in range(quiet_zone)]
    )
    if len(padded) % 2:
        padded.append(white_row.copy())

    lines: list[str] = []
    for row_index in range(0, len(padded), 2):
        top = padded[row_index]
        bottom = padded[row_index + 1]
        lines.append(
            "".join(
                _qr_half_block(top_cell, bottom_cell)
                for top_cell, bottom_cell in zip(top, bottom)
            )
        )
    return "\n".join(lines)


def _qr_half_block(top: int, bottom: int) -> str:
    if top and bottom:
        return "█"
    if top:
        return "▀"
    if bottom:
        return "▄"
    return " "


def normalize_attachment(value: object) -> Attachment | None:
    if isinstance(value, str):
        return Attachment(local_path=Path(value).expanduser())
    if not isinstance(value, dict):
        return None

    local_path = (
        value.get("local_path")
        or value.get("localPath")
        or value.get("storedFilename")
        or value.get("path")
    )
    filename = value.get("filename") or value.get("fileName")
    return Attachment(
        content_type=_optional_str(value.get("content_type") or value.get("contentType")),
        filename=_optional_str(filename),
        local_path=Path(str(local_path)).expanduser() if local_path else None,
        size_bytes=_optional_int(
            value.get("size_bytes") or value.get("sizeBytes") or value.get("size")
        ),
        source_id=_optional_str(value.get("source_id") or value.get("sourceId") or value.get("id")),
    )


def normalize_attachments(value: object) -> tuple[Attachment, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(
        attachment
        for item in value
        if (attachment := normalize_attachment(item)) is not None
    )


def _optional_str(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except ValueError:
        return None
