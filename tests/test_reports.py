from datetime import UTC, datetime

from post_office.models import Message, Source
from post_office.outputs.printer import format_receipt
from post_office.reports.daily import render_daily_report


def test_daily_report_renders_messages() -> None:
    message = Message(
        source=Source.INSTAGRAM,
        source_account_id="account",
        chat_id="chat",
        chat_name="Friends",
        sender_id="sender",
        sender_name="Salomon",
        timestamp=datetime(2026, 6, 11, 8, 30, tzinfo=UTC),
        text="hello",
    )

    report = render_daily_report(
        [message],
        window_start=datetime(2026, 6, 10, tzinfo=UTC),
        window_end=datetime(2026, 6, 11, tzinfo=UTC),
    )

    assert "Friends" in report
    assert "Salomon: hello" in report


def test_receipt_formats_message() -> None:
    message = Message(
        source=Source.SIGNAL,
        source_account_id="account",
        chat_id="chat",
        sender_id="sender",
        timestamp=datetime(2026, 6, 11, 8, 30, tzinfo=UTC),
        text="hello printer",
    )

    receipt = format_receipt(message)

    assert "SIGNAL" in receipt
    assert "hello printer" in receipt
