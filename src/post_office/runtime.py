from __future__ import annotations

from dataclasses import dataclass

from post_office.db import Database
from post_office.filters import BanList
from post_office.models import BanRule, Message
from post_office.outputs.printer import ThermalPrinter

PRINTER_TARGET = "printer"


@dataclass(frozen=True)
class IngestResult:
    inserted: bool
    allowed: bool
    matching_rule: BanRule | None = None

    @property
    def status(self) -> str:
        if not self.inserted:
            return "duplicate"
        if not self.allowed:
            return "banned"
        return "inserted"


@dataclass(frozen=True)
class PrintResult:
    message_id: str
    delivered: bool
    receipt: str | None = None
    error: str | None = None


class IngestionService:
    def __init__(self, database: Database, banlist: BanList) -> None:
        self.database = database
        self.banlist = banlist

    def ingest(self, message: Message) -> IngestResult:
        inserted = self.database.insert_message(message)
        matching_rule = self.banlist.matching_rule(message)
        return IngestResult(
            inserted=inserted,
            allowed=matching_rule is None,
            matching_rule=matching_rule,
        )


class LivePrinterService:
    def __init__(self, database: Database, banlist: BanList, printer: ThermalPrinter) -> None:
        self.database = database
        self.banlist = banlist
        self.printer = printer

    def process_pending(self) -> list[PrintResult]:
        results: list[PrintResult] = []
        for message in self.database.undelivered_messages(PRINTER_TARGET):
            if not self.banlist.allows(message):
                self.database.record_delivery(message.id, PRINTER_TARGET, "filtered")
                results.append(PrintResult(message_id=message.id, delivered=False))
                continue
            try:
                receipt = self.printer.print_message(message)
            except Exception as exc:  # noqa: BLE001 - delivery errors must be recorded and retried later
                self.database.record_delivery(message.id, PRINTER_TARGET, "failed", str(exc))
                results.append(PrintResult(message_id=message.id, delivered=False, error=str(exc)))
                continue
            self.database.record_delivery(message.id, PRINTER_TARGET, "delivered")
            results.append(PrintResult(message_id=message.id, delivered=True, receipt=receipt))
        return results
