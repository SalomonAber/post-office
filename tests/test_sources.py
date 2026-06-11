from post_office.config import SignalConfig
from post_office.models import Source
from post_office.sources.instagram import normalize_instagram_item
from post_office.sources.signal import (
    normalize_signal_event,
    parse_signal_accounts,
    parse_signal_json_line,
    parse_signal_json_output,
    signal_list_accounts_command,
    signal_receive_command,
)
from post_office.sources.whatsapp import normalize_baileys_event


def test_signal_receive_command_uses_json_and_timeout() -> None:
    command = signal_receive_command(
        SignalConfig(
            enabled=True,
            signal_cli="signal-cli",
            account="+49123",
            receive_timeout_seconds=60,
        )
    )
    assert command == (
        "signal-cli",
        "-a",
        "+49123",
        "-o",
        "json",
        "receive",
        "--timeout",
        "60",
    )


def test_signal_list_accounts_command() -> None:
    command = signal_list_accounts_command(SignalConfig(enabled=True, signal_cli="signal-cli"))

    assert command == ("signal-cli", "listAccounts")


def test_parse_signal_accounts_reads_number_lines() -> None:
    output = """
    INFO  AccountHelper - The Signal protocol expects regular receives.
    Number: +4916096508449
    """

    assert parse_signal_accounts(output) == ("+4916096508449",)


def test_parse_signal_json_line_accepts_object_and_array() -> None:
    assert parse_signal_json_line('{"envelope": {}}') == ({"envelope": {}},)
    assert parse_signal_json_line('[{"envelope": {}}, {"receipt": {}}]') == (
        {"envelope": {}},
        {"receipt": {}},
    )


def test_parse_signal_json_output_accepts_empty_and_pretty_json() -> None:
    assert parse_signal_json_output("") == ()
    assert parse_signal_json_output(
        """
        [
          {"envelope": {"sourceNumber": "+49123"}}
        ]
        """
    ) == ({"envelope": {"sourceNumber": "+49123"}},)


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
