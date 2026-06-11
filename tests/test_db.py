from datetime import UTC, datetime

from post_office.db import Database
from post_office.models import Message, Source


def test_insert_deduplicates_messages(tmp_path) -> None:
    database = Database(tmp_path / "post-office.sqlite3")
    database.migrate()
    message = Message(
        source=Source.WHATSAPP,
        source_account_id="account",
        chat_id="chat",
        sender_id="sender",
        source_message_id="source-id",
        timestamp=datetime(2026, 6, 11, tzinfo=UTC),
        text="hello",
    )

    assert database.insert_message(message)
    assert not database.insert_message(message)
    assert len(database.list_messages()) == 1
