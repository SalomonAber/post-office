from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from post_office.config import load_config, validate_config
from post_office.db import Database
from post_office.filters import BanList
from post_office.models import Message
from post_office.outputs.email import EmailSender
from post_office.reports.daily import render_daily_report
from post_office.sources.instagram import normalize_instagram_item
from post_office.sources.signal import normalize_signal_event
from post_office.sources.whatsapp import normalize_baileys_event


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="post-office")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db")
    subparsers.add_parser("validate-config")
    subparsers.add_parser("daily-report")

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
        if not banlist.allows(message):
            print("message ignored by ban-list")
            return 0
        inserted = database.insert_message(message)
        print("inserted" if inserted else "duplicate")
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


if __name__ == "__main__":
    raise SystemExit(main())
