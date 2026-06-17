from datetime import UTC, datetime

from post_office.config import PrinterConfig
from post_office.db import Database
from post_office.filters import BanList
from post_office.models import BanRule, Message, Source
from post_office.outputs.printer import ThermalPrinter
from post_office.runtime import (
    PRINTER_TARGET,
    Daemon,
    IngestResult,
    MessagePipeline,
    PipelineResult,
    ingest_message,
    print_message,
    print_pending_messages,
)


class RecordingPrinter:
    def __init__(self) -> None:
        self.message_ids: list[str] = []

    def print_message(self, message: Message) -> list[str]:
        self.message_ids.append(message.id)
        return [message.id]


class CountingBanList(BanList):
    def __init__(self) -> None:
        super().__init__(())
        self.match_count = 0

    def matching_rule(self, message: Message) -> BanRule | None:
        self.match_count += 1
        return super().matching_rule(message)


class NoopPipeline:
    def process(self, message: Message) -> PipelineResult:
        return PipelineResult(
            ingest=IngestResult(inserted=True, allowed=True),
            print=None,
        )


class OneMessageSource:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    async def messages(self):
        self.events.append(f"messages:{self.name}")
        yield message(source_message_id=self.name)


class PreparedOneMessageSource(OneMessageSource):
    async def prepare(self) -> None:
        self.events.append(f"prepare:{self.name}")


def message(*, sender_id: str = "sender", source_message_id: str = "source-id") -> Message:
    return Message(
        source=Source.SIGNAL,
        chat_id="chat",
        sender_id=sender_id,
        source_message_id=source_message_id,
        timestamp=datetime(2026, 6, 11, tzinfo=UTC),
        text="hello",
    )


def test_ingest_message_reports_banned_insert(tmp_path) -> None:
    database = Database(tmp_path / "post-office.sqlite3")
    database.migrate()
    banlist = BanList((BanRule(source=Source.SIGNAL, kind="sender_id", value="sender"),))

    result = ingest_message(database, banlist, message())

    assert result.inserted
    assert not result.allowed
    assert result.status == "banned"
    assert len(database.list_messages()) == 1


def test_live_printer_records_delivery_for_allowed_message(tmp_path) -> None:
    database = Database(tmp_path / "post-office.sqlite3")
    database.migrate()
    database.insert_message(message())
    printer = ThermalPrinter(PrinterConfig(enabled=False))

    results = print_pending_messages(database, BanList(()), printer)

    assert len(results) == 1
    assert results[0].status == "delivered"
    assert results[0].delivered
    assert database.undelivered_messages(PRINTER_TARGET) == []


def test_live_printer_marks_banned_message_filtered(tmp_path) -> None:
    database = Database(tmp_path / "post-office.sqlite3")
    database.migrate()
    database.insert_message(message())
    banlist = BanList((BanRule(source=Source.SIGNAL, kind="sender_id", value="sender"),))
    printer = ThermalPrinter(PrinterConfig(enabled=False))

    results = print_pending_messages(database, banlist, printer)

    assert len(results) == 1
    assert results[0].status == "filtered"
    assert not results[0].delivered
    assert database.undelivered_messages(PRINTER_TARGET) == []


def test_print_message_marks_one_banned_message_filtered(tmp_path) -> None:
    database = Database(tmp_path / "post-office.sqlite3")
    database.migrate()
    banned = message()
    database.insert_message(banned)
    banlist = BanList((BanRule(source=Source.SIGNAL, kind="sender_id", value="sender"),))
    printer = RecordingPrinter()

    result = print_message(database, printer, banned, allowed=banlist.allows(banned))

    assert result.status == "filtered"
    assert printer.message_ids == []
    assert database.undelivered_messages(PRINTER_TARGET) == []


def test_pipeline_ingests_and_prints_allowed_message(tmp_path) -> None:
    database = Database(tmp_path / "post-office.sqlite3")
    database.migrate()
    banlist = CountingBanList()
    printer = ThermalPrinter(PrinterConfig(enabled=False))
    pipeline = MessagePipeline(database, banlist, printer)

    result = pipeline.process(message())

    assert result.ingest.status == "inserted"
    assert result.print is not None
    assert result.print.status == "delivered"
    assert result.print.delivered
    assert banlist.match_count == 1


def test_pipeline_records_banned_message_as_filtered(tmp_path) -> None:
    database = Database(tmp_path / "post-office.sqlite3")
    database.migrate()
    banlist = BanList((BanRule(source=Source.SIGNAL, kind="sender_id", value="sender"),))
    printer = RecordingPrinter()
    pipeline = MessagePipeline(database, banlist, printer)

    result = pipeline.process(message())

    assert result.ingest.status == "banned"
    assert result.print is not None
    assert result.print.status == "filtered"
    assert printer.message_ids == []
    assert database.undelivered_messages(PRINTER_TARGET) == []


def test_pipeline_prints_only_the_new_message(tmp_path) -> None:
    database = Database(tmp_path / "post-office.sqlite3")
    database.migrate()
    old_message = message(source_message_id="old")
    database.insert_message(old_message)
    database.record_delivery(old_message.id, PRINTER_TARGET, "failed", "paper out")
    printer = RecordingPrinter()
    pipeline = MessagePipeline(database, BanList(()), printer)

    result = pipeline.process(message(source_message_id="new"))

    assert result.print is not None
    assert printer.message_ids == [result.print.message_id]
    assert printer.message_ids != [old_message.id]


def test_pipeline_skips_printing_duplicate_message(tmp_path) -> None:
    database = Database(tmp_path / "post-office.sqlite3")
    database.migrate()
    existing = message()
    database.insert_message(existing)
    pipeline = MessagePipeline(database, BanList(()), RecordingPrinter())

    result = pipeline.process(existing)

    assert result.ingest.status == "duplicate"
    assert result.print is None


def test_daemon_prepares_sources_before_starting_messages() -> None:
    events: list[str] = []
    daemon = Daemon(
        (
            PreparedOneMessageSource("signal", events),
            OneMessageSource("whatsapp", events),
        ),
        NoopPipeline(),  # type: ignore[arg-type]
    )

    import asyncio

    asyncio.run(daemon.run())

    assert events == ["prepare:signal", "messages:signal", "messages:whatsapp"]
