from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from post_office.models import Message


class SourceAdapter(Protocol):
    def messages(self) -> AsyncIterator[Message]:
        """Yield normalized messages from the source."""
        ...
