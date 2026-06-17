from datetime import UTC, datetime

from post_office.db import Database
from post_office.models import Attachment, Message, Source


def test_insert_deduplicates_messages(tmp_path) -> None:
    database = Database(tmp_path / "post-office.sqlite3")
    database.migrate()
    message = Message(
        source=Source.WHATSAPP,
        chat_id="chat",
        is_group_chat=True,
        sender_id="sender",
        source_message_id="source-id",
        timestamp=datetime(2026, 6, 11, tzinfo=UTC),
        text="hello",
        attachments=(
            Attachment(content_type="image/png", local_path=tmp_path / "image.png"),
        ),
    )

    assert database.insert_message(message)
    assert not database.insert_message(message)
    messages = database.list_messages()
    assert len(messages) == 1
    assert messages[0].is_group_chat
    assert messages[0].attachments[0].local_path == tmp_path / "image.png"
