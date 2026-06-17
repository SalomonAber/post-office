from datetime import UTC, datetime
from pathlib import Path

import pytest

from post_office.config import PrinterConfig
from post_office.models import Attachment, Message, Source
from post_office.outputs.printer import (
    ThermalPrinter,
    date_separator_lines,
    format_cpcl,
    format_image_placeholders,
    format_receipt,
    image_attachments,
)


def test_receipt_formats_message() -> None:
    receipt = format_receipt(message())

    assert "SIGNAL" in receipt[0]
    assert any("hello" in line for line in receipt)
    assert any("printer" in line for line in receipt)


def test_receipt_includes_chat_name_for_group_messages() -> None:
    receipt = format_receipt(
        message(chat_name="Family", sender_name="Alice", is_group_chat=True),
        width=80,
    )

    assert "Family > Alice" in receipt[0]


def test_receipt_omits_chat_name_for_direct_messages() -> None:
    receipt = format_receipt(
        message(chat_name="Alice", sender_name="Alice", is_group_chat=False),
        width=80,
    )

    assert "Alice > Alice" not in receipt[0]


def test_date_separator_formats_new_day_centered() -> None:
    lines = date_separator_lines(
        datetime(2026, 6, 11, 23, 59, tzinfo=UTC).date(),
        datetime(2026, 6, 12, 0, 1, tzinfo=UTC).date(),
        width=32,
    )

    assert lines == ["", "2026-06-12".center(32), ""]


def test_disabled_printer_formats_date_separator_after_day_changes() -> None:
    printer = ThermalPrinter(PrinterConfig(enabled=False, width_chars=32))

    first = printer.print_message(
        message(timestamp=datetime(2026, 6, 11, 23, 59, tzinfo=UTC))
    )
    second = printer.print_message(
        message(timestamp=datetime(2026, 6, 12, 0, 1, tzinfo=UTC))
    )

    assert first[0].startswith("23:59")
    assert second[:3] == ["", "2026-06-12".center(32), ""]
    assert second[3].startswith("00:01")


def test_cpcl_formats_message() -> None:
    cpcl = format_cpcl(message(text="hello zebra"), width=32)

    assert cpcl.startswith("! 0 200 200 ")
    assert "PAGE-WIDTH 576" in cpcl
    assert "08:30 SIGNAL sender: hello zebra" in cpcl
    assert "hello zebra" in cpcl
    assert cpcl.endswith("ENDML\r\nPRINT\r\n")


def test_printer_writes_date_separator_to_cpcl_when_day_changes(tmp_path) -> None:
    device_path = tmp_path / "rfcomm0"
    device_path.touch()
    printer = ThermalPrinter(
        PrinterConfig(
            enabled=True,
            device_path=device_path,
            width_chars=32,
        )
    )

    printer.print_message(message(timestamp=datetime(2026, 6, 11, 23, 59, tzinfo=UTC)))
    printer.print_message(message(timestamp=datetime(2026, 6, 12, 0, 1, tzinfo=UTC)))

    cpcl = device_path.read_bytes()
    assert f"\r\n{'2026-06-12'.center(32)}\r\n".encode() in cpcl
    assert b"00:01 SIGNAL sender: hello " in cpcl
    assert b"printer" in cpcl


def test_image_attachments_selects_local_images(tmp_path) -> None:
    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"placeholder")
    note_path = tmp_path / "note.txt"
    note_path.write_text("hello")

    images = image_attachments(
        message(
            attachments=(
                Attachment(content_type="image/png", local_path=image_path),
                Attachment(content_type="text/plain", local_path=note_path),
                Attachment(content_type="image/jpeg"),
            )
        )
    )

    assert images == (Attachment(content_type="image/png", local_path=image_path),)


def test_image_attachments_sniffs_extensionless_images(tmp_path) -> None:
    image_path = create_test_image(tmp_path / "signal-cli-attachment")

    images = image_attachments(
        message(attachments=(Attachment(local_path=image_path),))
    )

    assert images == (Attachment(local_path=image_path),)


def test_receipt_formats_image_only_message(tmp_path) -> None:
    image_path = create_test_image(tmp_path / "signal-cli-attachment")

    receipt = format_receipt(
        message(text="", attachments=(Attachment(local_path=image_path),)),
        width=80,
    )

    assert "[image]" in receipt[0]
    assert "[non-text message]" not in receipt[0]


def test_image_attachments_skips_missing_files(tmp_path) -> None:
    missing = tmp_path / "missing.png"

    assert image_attachments(
        message(attachments=(Attachment(content_type="image/png", local_path=missing),))
    ) == ()


def test_disabled_printer_receipt_includes_image_placeholder(tmp_path) -> None:
    image_path = create_test_image(tmp_path / "image.png")
    printer = ThermalPrinter(
        PrinterConfig(enabled=False, width_chars=80)
    )

    receipt = printer.print_message(
        message(attachments=(Attachment(content_type="image/png", local_path=image_path),))
    )

    assert "[image:" in " ".join(receipt)
    assert "image.png]" in " ".join(receipt)


def test_image_placeholders_wrap_paths(tmp_path) -> None:
    image_path = tmp_path / "a-very-long-image-name.png"

    lines = format_image_placeholders(
        (Attachment(content_type="image/png", local_path=image_path),),
        width=16,
    )

    assert lines
    assert lines[0].startswith("[image:")


def test_cpcl_embeds_image_attachment(tmp_path) -> None:
    image_path = create_test_image(tmp_path / "image.png")

    cpcl = format_cpcl(
        message(
            text="photo",
            attachments=(Attachment(content_type="image/png", local_path=image_path),),
        ),
        width=1,
    )

    assert "\r\nEG 1 4 " in cpcl
    assert "F000000F" in cpcl
    assert cpcl.endswith("PRINT\r\n")


def test_cpcl_uses_32px_margin_between_images(tmp_path) -> None:
    first = create_test_image(tmp_path / "first.png")
    second = create_test_image(tmp_path / "second.png")

    cpcl = format_cpcl(
        message(
            text="photos",
            attachments=(
                Attachment(content_type="image/png", local_path=first),
                Attachment(content_type="image/png", local_path=second),
            ),
        ),
        width=80,
    )

    assert "\r\nEG 1 4 284 28 " in cpcl
    assert "\r\nEG 1 4 284 64 " in cpcl


def test_cpcl_limits_image_height_to_half_page_width(tmp_path) -> None:
    image_path = create_test_image(tmp_path / "large.png", size=(1000, 800))

    cpcl = format_cpcl(
        message(attachments=(Attachment(content_type="image/png", local_path=image_path),)),
        width=48,
    )

    assert "\r\nEG 45 288 " in cpcl


def test_cpcl_rotates_portrait_image_before_scaling(tmp_path) -> None:
    image_path = create_test_image(tmp_path / "portrait.png", size=(8, 1000))

    cpcl = format_cpcl(
        message(attachments=(Attachment(content_type="image/png", local_path=image_path),)),
        width=48,
    )

    assert "\r\nEG 48 3 " in cpcl


def test_printer_writes_cpcl_to_device_file(tmp_path) -> None:
    device_path = tmp_path / "rfcomm0"
    device_path.touch()
    printer = ThermalPrinter(
        PrinterConfig(
            enabled=True,
            device_path=device_path,
        )
    )

    receipt = printer.print_message(message(text="hello bluetooth"))

    assert "hello bluetooth" in " ".join(receipt)
    assert b"hello bluetooth" in device_path.read_bytes()
    assert device_path.read_bytes().startswith(b"! 0 200 200 ")


def test_printer_fails_when_device_path_is_missing(tmp_path) -> None:
    printer = ThermalPrinter(
        PrinterConfig(
            enabled=True,
            device_path=tmp_path / "missing-rfcomm0",
        )
    )

    with pytest.raises(RuntimeError, match="printer device does not exist"):
        printer.print_message(message(text="hello bluetooth"))


def test_printer_deletes_images_after_print(tmp_path) -> None:
    device_path = tmp_path / "rfcomm0"
    device_path.touch()
    image_path = create_test_image(tmp_path / "delete-me.png")
    printer = ThermalPrinter(
        PrinterConfig(
            enabled=True,
            device_path=device_path,
        )
    )

    printer.print_message(
        message(attachments=(Attachment(content_type="image/png", local_path=image_path),))
    )

    assert not image_path.exists()


def message(
    *,
    text: str = "hello printer",
    chat_name: str | None = None,
    sender_name: str | None = None,
    is_group_chat: bool = False,
    attachments: tuple[Attachment, ...] = (),
    timestamp: datetime | None = None,
) -> Message:
    return Message(
        source=Source.SIGNAL,
        chat_id="chat",
        chat_name=chat_name,
        is_group_chat=is_group_chat,
        sender_id="sender",
        sender_name=sender_name,
        timestamp=timestamp or datetime(2026, 6, 11, 8, 30, tzinfo=UTC),
        text=text,
        attachments=attachments,
    )


def create_test_image(path: Path, *, size: tuple[int, int] = (8, 4)) -> Path:
    from PIL import Image  # type: ignore[import-untyped]

    image = Image.new("1", size, 1)
    for x in range(min(4, size[0])):
        image.putpixel((x, 0), 0)
    for x in range(min(4, size[0]), size[0]):
        image.putpixel((x, size[1] - 1), 0)
    image.save(path, format="PNG")
    return path
