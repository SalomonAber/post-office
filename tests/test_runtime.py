from datetime import UTC, datetime

from post_office.config import PrinterConfig
from post_office.db import Database
from post_office.filters import BanList
from post_office.models import BanRule, Message, Source
from post_office.outputs.printer import ThermalPrinter
from post_office.runtime import (
    PRINTER_TARGET,
    IngestionService,
    LivePrinterService,
    MessagePipeline,
)


def message(*, sender_id: str = "sender", source_message_id: str = "source-id") -> Message:
    return Message(
        source=Source.SIGNAL,
        source_account_id="account",
        chat_id="chat",
        sender_id=sender_id,
        source_message_id=source_message_id,
        timestamp=datetime(2026, 6, 11, tzinfo=UTC),
        text="hello",
    )


def test_ingestion_service_reports_banned_insert(tmp_path) -> None:
    database = Database(tmp_path / "post-office.sqlite3")
    database.migrate()
    banlist = BanList((BanRule(source=Source.SIGNAL, kind="sender_id", value="sender"),))

    result = IngestionService(database, banlist).ingest(message())

    assert result.inserted
    assert not result.allowed
    assert result.status == "banned"
    assert len(database.list_messages()) == 1


def test_live_printer_records_delivery_for_allowed_message(tmp_path) -> None:
    database = Database(tmp_path / "post-office.sqlite3")
    database.migrate()
    database.insert_message(message())
    printer = ThermalPrinter(PrinterConfig(enabled=False, usb_vendor_id=None, usb_product_id=None))

    results = LivePrinterService(database, BanList(()), printer).process_pending()

    assert len(results) == 1
    assert results[0].delivered
    assert database.undelivered_messages(PRINTER_TARGET) == []


def test_live_printer_marks_banned_message_filtered(tmp_path) -> None:
    database = Database(tmp_path / "post-office.sqlite3")
    database.migrate()
    database.insert_message(message())
    banlist = BanList((BanRule(source=Source.SIGNAL, kind="sender_id", value="sender"),))
    printer = ThermalPrinter(PrinterConfig(enabled=False, usb_vendor_id=None, usb_product_id=None))

    results = LivePrinterService(database, banlist, printer).process_pending()

    assert len(results) == 1
    assert not results[0].delivered
    assert database.undelivered_messages(PRINTER_TARGET) == []


def test_pipeline_ingests_and_prints_allowed_message(tmp_path) -> None:
    database = Database(tmp_path / "post-office.sqlite3")
    database.migrate()
    banlist = BanList(())
    printer = ThermalPrinter(PrinterConfig(enabled=False, usb_vendor_id=None, usb_product_id=None))
    pipeline = MessagePipeline(
        IngestionService(database, banlist),
        LivePrinterService(database, banlist, printer),
    )

    result = pipeline.process(message())

    assert result.ingest.status == "inserted"
    assert len(result.prints) == 1
    assert result.prints[0].delivered
