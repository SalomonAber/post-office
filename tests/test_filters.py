from datetime import UTC, datetime

from post_office.filters import BanList
from post_office.models import BanRule, Message, Source


def message() -> Message:
    return Message(
        source=Source.SIGNAL,
        chat_id="chat-1",
        sender_id="sender-1",
        timestamp=datetime(2026, 6, 11, tzinfo=UTC),
        text="hello",
    )


def test_banlist_blocks_sender() -> None:
    banlist = BanList((BanRule(source=Source.SIGNAL, kind="sender_id", value="sender-1"),))

    assert not banlist.allows(message())


def test_banlist_allows_different_source() -> None:
    banlist = BanList((BanRule(source=Source.WHATSAPP, kind="sender_id", value="sender-1"),))

    assert banlist.allows(message())
