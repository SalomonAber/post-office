from post_office.models import Source
from post_office.sources.instagram import normalize_instagram_item
from post_office.sources.signal import normalize_signal_event
from post_office.sources.whatsapp import normalize_baileys_event


def test_normalize_whatsapp_event() -> None:
    message = normalize_baileys_event(
        {
            "key": {"remoteJid": "chat@g.us", "participant": "sender@s.whatsapp.net", "id": "abc"},
            "messageTimestamp": 1781164800,
            "message": {"conversation": "hello"},
        },
        account_id="account",
    )

    assert message is not None
    assert message.source == Source.WHATSAPP
    assert message.text == "hello"


def test_normalize_signal_event() -> None:
    message = normalize_signal_event(
        {
            "envelope": {
                "sourceNumber": "+49123",
                "timestamp": 1781164800000,
                "dataMessage": {"message": "hello signal", "timestamp": 1781164800000},
            }
        },
        account="account",
    )

    assert message is not None
    assert message.source == Source.SIGNAL
    assert message.text == "hello signal"


def test_normalize_instagram_item() -> None:
    message = normalize_instagram_item(
        {"id": "item-1", "user_id": "user-1", "timestamp": 1781164800, "text": "hello ig"},
        account_id="account",
        thread_id="thread-1",
    )

    assert message is not None
    assert message.source == Source.INSTAGRAM
    assert message.text == "hello ig"
