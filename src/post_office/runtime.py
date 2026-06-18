from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol

from post_office.db import Database
from post_office.filters import BanList
from post_office.models import BanRule, Message
from post_office.sources.base import PreparableSourceAdapter, SourceAdapter

PRINTER_TARGET = "printer"
PrintStatus = Literal["delivered", "filtered", "failed"]

logger = logging.getLogger(__name__)


class ReceiptPrinter(Protocol):
    def print_message(self, message: Message) -> list[str]:
        ...


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
    status: PrintStatus
    receipt: list[str] | None = None
    error: str | None = None

    @property
    def delivered(self) -> bool:
        return self.status == "delivered"


def ingest_message(database: Database, banlist: BanList, message: Message) -> IngestResult:
    matching_rule = banlist.matching_rule(message)
    return IngestResult(
        inserted=database.insert_message(message),
        allowed=matching_rule is None,
        matching_rule=matching_rule,
    )


def print_message(
    database: Database,
    printer: ReceiptPrinter,
    message: Message,
    *,
    allowed: bool,
) -> PrintResult:
    if not allowed:
        database.record_delivery(message.id, PRINTER_TARGET, "filtered")
        return PrintResult(message_id=message.id, status="filtered")

    try:
        receipt = printer.print_message(message)
    except Exception as exc:  # noqa: BLE001 - delivery errors must be recorded and retried later
        error = str(exc)
        logger.exception(
            "failed to print message source=%s chat_id=%s sender_id=%s message_id=%s: %s",
            message.source.value,
            message.chat_id,
            message.sender_id,
            message.id,
            error,
        )
        database.record_delivery(message.id, PRINTER_TARGET, "failed", error)
        return PrintResult(message_id=message.id, status="failed", error=error)

    database.record_delivery(message.id, PRINTER_TARGET, "delivered")
    return PrintResult(message_id=message.id, status="delivered", receipt=receipt)


def print_pending_messages(
    database: Database,
    banlist: BanList,
    printer: ReceiptPrinter,
) -> list[PrintResult]:
    return [
        print_message(database, printer, message, allowed=banlist.allows(message))
        for message in database.undelivered_messages(PRINTER_TARGET)
    ]


@dataclass(frozen=True)
class PipelineResult:
    ingest: IngestResult
    print: PrintResult | None


class MessagePipeline:
    def __init__(self, database: Database, banlist: BanList, printer: ReceiptPrinter) -> None:
        self.database = database
        self.banlist = banlist
        self.printer = printer

    def process(self, message: Message) -> PipelineResult:
        ingest = ingest_message(self.database, self.banlist, message)
        if not ingest.inserted:
            return PipelineResult(ingest=ingest, print=None)
        return PipelineResult(
            ingest=ingest,
            print=print_message(self.database, self.printer, message, allowed=ingest.allowed),
        )


class Daemon:
    def __init__(self, sources: Iterable[SourceAdapter], pipeline: MessagePipeline) -> None:
        self.sources = tuple(sources)
        self.pipeline = pipeline

    async def run(self) -> None:
        if not self.sources:
            msg = "at least one source must be enabled"
            raise RuntimeError(msg)
        for source in self.sources:
            if isinstance(source, PreparableSourceAdapter):
                await source.prepare()
        await asyncio.gather(*(self._run_source(source) for source in self.sources))

    async def _run_source(self, source: SourceAdapter) -> None:
        async for message in source.messages():
            result = self.pipeline.process(message)
            logger.info(
                "processed message source=%s chat_id=%s sender_id=%s status=%s print_status=%s",
                message.source.value,
                message.chat_id,
                message.sender_id,
                result.ingest.status,
                result.print.status if result.print else "skipped",
            )
