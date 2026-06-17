from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from post_office.models import BanRule, Source


@dataclass(frozen=True)
class PrinterConfig:
    enabled: bool = False
    device_path: Path = Path("/dev/rfcomm0")
    width_chars: int = 42


@dataclass(frozen=True)
class SignalConfig:
    enabled: bool = False
    data_dir: Path = Path("./state/signal-cli")
    media_dir: Path = Path("./state/media/signal")
    include_own_messages: bool = False
    restart_delay_seconds: int = 5
    max_restart_delay_seconds: int = 300


@dataclass(frozen=True)
class WhatsAppConfig:
    enabled: bool = False
    auth_dir: Path = Path("./state/whatsapp-auth")
    media_dir: Path = Path("./state/media/whatsapp")
    include_own_messages: bool = False
    restart_delay_seconds: int = 5
    max_restart_delay_seconds: int = 300


@dataclass(frozen=True)
class SourcesConfig:
    signal: SignalConfig = field(default_factory=SignalConfig)
    whatsapp: WhatsAppConfig = field(default_factory=WhatsAppConfig)


@dataclass(frozen=True)
class AppConfig:
    timezone: str
    database_path: Path
    state_dir: Path
    ban_rules: tuple[BanRule, ...]
    printer: PrinterConfig
    sources: SourcesConfig


def load_config(path: Path) -> AppConfig:
    data = tomllib.loads(path.read_text())
    app = data.get("app", {})
    banlist = data.get("banlist", {})
    printer = data.get("printer", {})
    sources = data.get("sources", {})

    state_dir = Path(str(app.get("state_dir", "./state"))).expanduser()
    return AppConfig(
        timezone=str(app.get("timezone", "UTC")),
        database_path=state_dir / "post-office.sqlite3",
        state_dir=state_dir,
        ban_rules=_load_ban_rules(banlist),
        printer=_load_printer(printer),
        sources=SourcesConfig(
            signal=_load_signal(sources.get("signal", {}), state_dir=state_dir),
            whatsapp=_load_whatsapp(sources.get("whatsapp", {}), state_dir=state_dir),
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


def _load_printer(data: dict[str, Any]) -> PrinterConfig:
    return PrinterConfig(
        enabled=bool(data.get("enabled", False)),
        device_path=Path(str(data.get("device_path", "/dev/rfcomm0"))).expanduser(),
        width_chars=int(data.get("width_chars", 42)),
    )


def _load_signal(data: dict[str, Any], *, state_dir: Path) -> SignalConfig:
    default_data_dir = state_dir / "signal-cli"
    default_media_dir = state_dir / "media" / "signal"
    return SignalConfig(
        enabled=bool(data.get("enabled", False)),
        data_dir=Path(str(data.get("data_dir", default_data_dir))).expanduser(),
        media_dir=Path(str(data.get("media_dir", default_media_dir))).expanduser(),
        include_own_messages=bool(data.get("include_own_messages", False)),
        restart_delay_seconds=int(data.get("restart_delay_seconds", 5)),
        max_restart_delay_seconds=int(data.get("max_restart_delay_seconds", 300)),
    )


def _load_whatsapp(data: dict[str, Any], *, state_dir: Path) -> WhatsAppConfig:
    default_media_dir = state_dir / "media" / "whatsapp"
    return WhatsAppConfig(
        enabled=bool(data.get("enabled", False)),
        auth_dir=Path(str(data.get("auth_dir", "./state/whatsapp-auth"))).expanduser(),
        media_dir=Path(str(data.get("media_dir", default_media_dir))).expanduser(),
        include_own_messages=bool(data.get("include_own_messages", False)),
        restart_delay_seconds=int(data.get("restart_delay_seconds", 5)),
        max_restart_delay_seconds=int(data.get("max_restart_delay_seconds", 300)),
    )


def validate_config(config: AppConfig) -> list[str]:
    return []
