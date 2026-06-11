from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from post_office.models import BanRule, Source


@dataclass(frozen=True)
class EmailConfig:
    enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_starttls: bool
    smtp_username: str
    smtp_password: str | None
    from_address: str
    to_addresses: tuple[str, ...]
    subject_prefix: str = "Post Office"


@dataclass(frozen=True)
class PrinterConfig:
    enabled: bool
    usb_vendor_id: int | None
    usb_product_id: int | None
    dry_run: bool = True


@dataclass(frozen=True)
class SignalConfig:
    enabled: bool
    signal_cli: str = "signal-cli"
    account: str = ""


@dataclass(frozen=True)
class WhatsAppConfig:
    enabled: bool
    bridge_command: tuple[str, ...] = ("node", "whatsapp-bridge/index.js")


@dataclass(frozen=True)
class InstagramConfig:
    enabled: bool
    username: str = ""
    password: str | None = None
    poll_interval_seconds: int = 300


@dataclass(frozen=True)
class SourcesConfig:
    signal: SignalConfig = field(default_factory=lambda: SignalConfig(enabled=False))
    whatsapp: WhatsAppConfig = field(default_factory=lambda: WhatsAppConfig(enabled=False))
    instagram: InstagramConfig = field(default_factory=lambda: InstagramConfig(enabled=False))


@dataclass(frozen=True)
class AppConfig:
    timezone: str
    database_path: Path
    state_dir: Path
    ban_rules: tuple[BanRule, ...]
    email: EmailConfig
    printer: PrinterConfig
    sources: SourcesConfig


def load_config(path: Path) -> AppConfig:
    data = tomllib.loads(path.read_text())
    app = data.get("app", {})
    banlist = data.get("banlist", {})
    email = data.get("email", {})
    printer = data.get("printer", {})
    sources = data.get("sources", {})

    return AppConfig(
        timezone=str(app.get("timezone", "UTC")),
        database_path=Path(str(app.get("database_path", "./post-office.sqlite3"))).expanduser(),
        state_dir=Path(str(app.get("state_dir", "./state"))).expanduser(),
        ban_rules=_load_ban_rules(banlist),
        email=_load_email(email),
        printer=_load_printer(printer),
        sources=SourcesConfig(
            signal=_load_signal(sources.get("signal", {})),
            whatsapp=_load_whatsapp(sources.get("whatsapp", {})),
            instagram=_load_instagram(sources.get("instagram", {})),
        ),
    )


def _load_ban_rules(data: dict[str, Any]) -> tuple[BanRule, ...]:
    rules: list[BanRule] = []
    for item in data.get("sender_ids", []):
        rules.append(_ban_rule(item, "sender_id"))
    for item in data.get("chat_ids", []):
        rules.append(_ban_rule(item, "chat_id"))
    return tuple(rules)


def _ban_rule(item: dict[str, Any], kind: str) -> BanRule:
    return BanRule(
        source=Source(str(item["source"])),
        kind=kind,
        value=str(item["id"]),
        reason=item.get("reason"),
        enabled=bool(item.get("enabled", True)),
    )


def _load_email(data: dict[str, Any]) -> EmailConfig:
    password_env = str(data.get("smtp_password_env", ""))
    return EmailConfig(
        enabled=bool(data.get("enabled", False)),
        smtp_host=str(data.get("smtp_host", "localhost")),
        smtp_port=int(data.get("smtp_port", 587)),
        smtp_starttls=bool(data.get("smtp_starttls", True)),
        smtp_username=str(data.get("smtp_username", "")),
        smtp_password=os.environ.get(password_env) if password_env else None,
        from_address=str(data.get("from_address", "post-office@localhost")),
        to_addresses=tuple(str(address) for address in data.get("to_addresses", [])),
        subject_prefix=str(data.get("subject_prefix", "Post Office")),
    )


def _load_printer(data: dict[str, Any]) -> PrinterConfig:
    return PrinterConfig(
        enabled=bool(data.get("enabled", False)),
        usb_vendor_id=_parse_int(data.get("usb_vendor_id")),
        usb_product_id=_parse_int(data.get("usb_product_id")),
        dry_run=bool(data.get("dry_run", True)),
    )


def _load_signal(data: dict[str, Any]) -> SignalConfig:
    return SignalConfig(
        enabled=bool(data.get("enabled", False)),
        signal_cli=str(data.get("signal_cli", "signal-cli")),
        account=str(data.get("account", "")),
    )


def _load_whatsapp(data: dict[str, Any]) -> WhatsAppConfig:
    default_command = ["node", "whatsapp-bridge/index.js"]
    return WhatsAppConfig(
        enabled=bool(data.get("enabled", False)),
        bridge_command=tuple(str(part) for part in data.get("bridge_command", default_command)),
    )


def _load_instagram(data: dict[str, Any]) -> InstagramConfig:
    password_env = str(data.get("password_env", ""))
    return InstagramConfig(
        enabled=bool(data.get("enabled", False)),
        username=str(data.get("username", "")),
        password=os.environ.get(password_env) if password_env else None,
        poll_interval_seconds=int(data.get("poll_interval_seconds", 300)),
    )


def _parse_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    return int(str(value), 0)


def validate_config(config: AppConfig) -> list[str]:
    errors: list[str] = []
    if config.email.enabled:
        if not config.email.to_addresses:
            errors.append("email.to_addresses must not be empty when email is enabled")
        if not config.email.from_address:
            errors.append("email.from_address must not be empty when email is enabled")
    if (
        config.printer.enabled
        and not config.printer.dry_run
        and (config.printer.usb_vendor_id is None or config.printer.usb_product_id is None)
    ):
        errors.append("printer USB vendor/product IDs are required unless dry_run is true")
    if config.sources.signal.enabled and not config.sources.signal.account:
        errors.append("sources.signal.account is required when Signal is enabled")
    if config.sources.instagram.enabled and not config.sources.instagram.username:
        errors.append("sources.instagram.username is required when Instagram is enabled")
    return errors
