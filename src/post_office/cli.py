from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from post_office.config import SignalConfig, SourcesConfig, load_config, validate_config
from post_office.db import Database
from post_office.filters import BanList
from post_office.models import Message
from post_office.outputs.email import EmailSender
from post_office.outputs.printer import ThermalPrinter
from post_office.reports.daily import render_daily_report
from post_office.runtime import Daemon, IngestionService, LivePrinterService, MessagePipeline
from post_office.sources.base import SourceAdapter
from post_office.sources.instagram import InstagramAdapter, normalize_instagram_item
from post_office.sources.signal import (
    SignalAdapter,
    normalize_signal_event,
    signal_account_is_registered,
)
from post_office.sources.whatsapp import WhatsAppBridgeAdapter, normalize_baileys_event


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="post-office")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db")
    subparsers.add_parser("validate-config")
    subparsers.add_parser("daily-report")
    subparsers.add_parser("print-pending")
    subparsers.add_parser("daemon")
    subparsers.add_parser("check-signal")

    ingest_fixture = subparsers.add_parser("ingest-fixture")
    ingest_fixture.add_argument("source", choices=["signal", "whatsapp", "instagram"])
    ingest_fixture.add_argument("path", type=Path)

    args = parser.parse_args(argv)
    config = load_config(args.config)

    if args.command == "validate-config":
        errors = validate_config(config)
        if errors:
            for error in errors:
                print(error)
            return 1
        print("configuration ok")
        return 0

    database = Database(config.database_path)
    if args.command == "init-db":
        database.migrate()
        print(f"initialized database at {config.database_path}")
        return 0

    database.migrate()
    banlist = BanList(config.ban_rules)

    if args.command == "ingest-fixture":
        event = json.loads(args.path.read_text())
        message = _fixture_message(args.source, event)
        if message is None:
            print("fixture did not contain a supported message")
            return 1
        result = IngestionService(database, banlist).ingest(message)
        print(result.status)
        return 0

    if args.command == "print-pending":
        printer = ThermalPrinter(config.printer)
        results = LivePrinterService(database, banlist, printer).process_pending()
        delivered = sum(1 for result in results if result.delivered)
        failed = sum(1 for result in results if result.error is not None)
        filtered = len(results) - delivered - failed
        print(f"delivered={delivered} filtered={filtered} failed={failed}")
        return 1 if failed else 0

    if args.command == "check-signal":
        return _check_signal(config.sources.signal)

    if args.command == "daemon":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        if config.sources.signal.enabled:
            signal_status = _check_signal(config.sources.signal)
            if signal_status != 0:
                return signal_status
        sources = _enabled_sources(config.sources)
        if not sources:
            print("no sources are enabled")
            return 1
        pipeline = MessagePipeline(
            IngestionService(database, banlist),
            LivePrinterService(database, banlist, ThermalPrinter(config.printer)),
        )
        try:
            asyncio.run(Daemon(sources, pipeline).run())
        except KeyboardInterrupt:
            return 0
        return 0

    if args.command == "daily-report":
        window_end = datetime.now(UTC)
        window_start = window_end - timedelta(days=1)
        all_messages = database.list_messages(start=window_start, end=window_end)
        messages = [m for m in all_messages if banlist.allows(m)]
        report = render_daily_report(messages, window_start=window_start, window_end=window_end)
        EmailSender(config.email).send(
            subject=window_start.strftime("Daily report %Y-%m-%d"),
            body=report,
        )
        print(report)
        return 0

    return 1


def _fixture_message(source: str, event: dict[str, Any]) -> Message | None:
    if source == "signal":
        return normalize_signal_event(event, account="fixture")
    if source == "whatsapp":
        return normalize_baileys_event(event, account_id="fixture")
    if source == "instagram":
        return normalize_instagram_item(
            event,
            account_id="fixture",
            thread_id=str(event.get("thread_id", "fixture")),
        )
    return None


def _enabled_sources(sources_config: SourcesConfig) -> tuple[SourceAdapter, ...]:
    sources: list[SourceAdapter] = []
    if sources_config.signal.enabled:
        sources.append(SignalAdapter(sources_config.signal))
    if sources_config.whatsapp.enabled:
        sources.append(WhatsAppBridgeAdapter(sources_config.whatsapp))
    if sources_config.instagram.enabled:
        sources.append(InstagramAdapter(sources_config.instagram))
    return tuple(sources)


def _check_signal(signal_config: SignalConfig) -> int:
    if not signal_config.enabled:
        print("Signal source is disabled")
        return 0
    account = signal_config.account
    if signal_account_is_registered(signal_config):
        print(f"Signal account is configured: {account}")
        return 0
    print(f"Signal account is not registered or linked locally: {account}")
    print("Run `signal-cli link -n post-office` to link this machine as a secondary device.")
    print("Then scan the printed `sgnl://linkdevice?...` URI from Signal on your phone.")
    print("After linking, run `signal-cli listAccounts` and retry `post-office ... check-signal`.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
