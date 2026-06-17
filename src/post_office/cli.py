from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from post_office.config import SourcesConfig, load_config, validate_config
from post_office.db import Database
from post_office.filters import BanList
from post_office.outputs.printer import ThermalPrinter
from post_office.runtime import Daemon, MessagePipeline, print_pending_messages
from post_office.sources.base import CheckableSourceAdapter, SourceAdapter
from post_office.sources.signal import SignalAdapter
from post_office.sources.whatsapp import WhatsAppAdapter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="post-office")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("print-pending")
    subparsers.add_parser("daemon")

    args = parser.parse_args(argv)
    config = load_config(args.config)
    errors = validate_config(config)
    if errors:
        for error in errors:
            print(error)
        return 1

    database = Database(config.database_path)
    database.migrate()
    banlist = BanList(config.ban_rules)

    if args.command == "print-pending":
        printer = ThermalPrinter(config.printer)
        results = print_pending_messages(database, banlist, printer)
        delivered = sum(1 for result in results if result.status == "delivered")
        filtered = sum(1 for result in results if result.status == "filtered")
        failed = sum(1 for result in results if result.status == "failed")
        print(f"delivered={delivered} filtered={filtered} failed={failed}")
        return 1 if failed else 0

    if args.command == "daemon":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        sources = _enabled_sources(config.sources)
        if not sources:
            print("no sources are enabled")
            return 1
        source_errors = _check_sources(sources)
        if source_errors:
            for error in source_errors:
                print(error)
            return 1
        pipeline = MessagePipeline(database, banlist, ThermalPrinter(config.printer))
        try:
            asyncio.run(Daemon(sources, pipeline).run())
        except KeyboardInterrupt:
            return 0
        return 0

    return 1


def _enabled_sources(sources_config: SourcesConfig) -> tuple[SourceAdapter, ...]:
    sources: list[SourceAdapter] = []
    if sources_config.signal.enabled:
        sources.append(SignalAdapter(sources_config.signal))
    if sources_config.whatsapp.enabled:
        sources.append(WhatsAppAdapter(sources_config.whatsapp))
    return tuple(sources)


def _check_sources(sources: tuple[SourceAdapter, ...]) -> tuple[str, ...]:
    errors: list[str] = []
    for source in sources:
        if isinstance(source, CheckableSourceAdapter):
            errors.extend(source.check())
    return tuple(errors)


if __name__ == "__main__":
    raise SystemExit(main())
