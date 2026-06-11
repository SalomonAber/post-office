from __future__ import annotations

import textwrap

from post_office.config import PrinterConfig
from post_office.models import Message


class ThermalPrinter:
    def __init__(self, config: PrinterConfig) -> None:
        self.config = config

    def print_message(self, message: Message) -> str:
        receipt = format_receipt(message)
        if not self.config.enabled or self.config.dry_run:
            return receipt
        if self.config.usb_vendor_id is None or self.config.usb_product_id is None:
            msg = "printer USB vendor/product IDs are required"
            raise RuntimeError(msg)
        try:
            from escpos.printer import Usb  # type: ignore[import-not-found]
        except ImportError as exc:
            msg = "python-escpos is required for non-dry-run printing"
            raise RuntimeError(msg) from exc

        printer = Usb(self.config.usb_vendor_id, self.config.usb_product_id)
        printer.text(receipt)
        printer.cut()
        return receipt


def format_receipt(message: Message, *, width: int = 42) -> str:
    chat = message.chat_name or message.chat_id
    sender = message.sender_name or message.sender_id
    header = f"{message.source.value.upper()} {message.timestamp:%Y-%m-%d %H:%M}"
    body = message.text.strip() or "[non-text message]"
    wrapped = "\n".join(textwrap.wrap(body, width=width, replace_whitespace=False))
    return f"{header}\n{chat}\n{sender}\n{'-' * width}\n{wrapped}\n\n"
