from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any
from uuid import uuid4


class Source(StrEnum):
    SIGNAL = "signal"
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"


@dataclass(frozen=True)
class Attachment:
    content_type: str | None = None
    filename: str | None = None
    size_bytes: int | None = None
    source_id: str | None = None


@dataclass(frozen=True)
class Message:
    source: Source
    source_account_id: str
    chat_id: str
    sender_id: str
    timestamp: datetime
    text: str
    source_message_id: str | None = None
    chat_name: str | None = None
    sender_name: str | None = None
    attachments: tuple[Attachment, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            object.__setattr__(self, "timestamp", self.timestamp.replace(tzinfo=UTC))
        if self.received_at.tzinfo is None:
            object.__setattr__(self, "received_at", self.received_at.replace(tzinfo=UTC))

    @property
    def dedupe_key(self) -> str:
        if self.source_message_id:
            return f"{self.source}:{self.source_account_id}:{self.chat_id}:{self.source_message_id}"
        material = "|".join(
            [
                self.source,
                self.source_account_id,
                self.chat_id,
                self.sender_id,
                self.timestamp.isoformat(),
                self.text,
            ]
        )
        return f"{self.source}:synthetic:{sha256(material.encode()).hexdigest()}"


@dataclass(frozen=True)
class BanRule:
    source: Source
    kind: str
    value: str
    reason: str | None = None
    enabled: bool = True

    def matches(self, message: Message) -> bool:
        if not self.enabled or self.source != message.source:
            return False
        if self.kind == "sender_id":
            return self.value == message.sender_id
        if self.kind == "chat_id":
            return self.value == message.chat_id
        msg = f"unsupported ban rule kind: {self.kind}"
        raise ValueError(msg)


@dataclass(frozen=True)
class Delivery:
    message_id: str
    target: str
    delivered_at: datetime
    status: str
    error: str | None = None
