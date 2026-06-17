from pathlib import Path

from post_office.config import SignalConfig, WhatsAppConfig
from post_office.models import Source
from post_office.sources.base import render_terminal_qr
from post_office.sources.signal import (
    normalize_signal_event,
    parse_signal_json_line,
    parse_signal_json_output,
    parse_signal_json_prefix,
    parse_signal_linked_numbers,
    signal_event_kind,
    signal_event_summary,
    signal_link_command,
    signal_list_linked_numbers_command,
    signal_receive_command,
    signal_retry_delay,
    summarize_signal_cli_error,
)
from post_office.sources.whatsapp import normalize_baileys_event, whatsapp_retry_delay


def test_signal_receive_command_uses_json_and_long_running_timeout() -> None:
    command = signal_receive_command(SignalConfig(enabled=True))

    assert command == (
        "signal-cli",
        "-o",
        "json",
        "receive",
        "--timeout",
        "-1",
    )


def test_signal_list_linked_numbers_command() -> None:
    command = signal_list_linked_numbers_command(SignalConfig(enabled=True))

    assert command == ("signal-cli", "listAccounts")


def test_signal_link_command_uses_post_office_device_name() -> None:
    command = signal_link_command(SignalConfig(enabled=True))

    assert command == (
        "signal-cli",
        "link",
        "-n",
        "post-office",
    )


def test_signal_commands_use_data_dir_flag_for_custom_state_path() -> None:
    config = SignalConfig(enabled=True, data_dir=Path("/var/lib/post-office/signal"))

    assert signal_link_command(config) == (
        "signal-cli",
        "-d",
        "/var/lib/post-office/signal",
        "link",
        "-n",
        "post-office",
    )


def test_signal_retry_delay_exponentially_backs_off() -> None:
    config = SignalConfig(
        enabled=True,
        restart_delay_seconds=5,
        max_restart_delay_seconds=20,
    )

    assert signal_retry_delay(config, 1) == 5
    assert signal_retry_delay(config, 2) == 10
    assert signal_retry_delay(config, 3) == 20
    assert signal_retry_delay(config, 4) == 20


def test_whatsapp_retry_delay_exponentially_backs_off() -> None:
    config = WhatsAppConfig(
        enabled=True,
        restart_delay_seconds=5,
        max_restart_delay_seconds=20,
    )

    assert whatsapp_retry_delay(config, 1) == 5
    assert whatsapp_retry_delay(config, 2) == 10
    assert whatsapp_retry_delay(config, 3) == 20
    assert whatsapp_retry_delay(config, 4) == 20


def test_summarize_signal_cli_error_compacts_retry_npe() -> None:
    stderr = "\n".join(
        [
            'java.lang.NullPointerException: Cannot invoke getSender() because "content" is null',
            "    at org.asamk.signal.manager.helper.ReceiveHelper.retryFailedReceivedMessage",
            "    at org.asamk.signal.Main.main(Main.java:57)",
        ]
    )

    assert summarize_signal_cli_error(stderr) == (
        'java.lang.NullPointerException: Cannot invoke getSender() because "content" is null '
        "while retrying cached failed Signal messages"
    )


def test_summarize_signal_cli_error_prefers_argparse_error() -> None:
    stderr = "\n".join(
        [
            "usage: signal-cli [-h] [--version]",
            "usage: signal-cli link [-h] [-n NAME]",
            "signal-cli: error: unrecognized arguments: --bad",
        ]
    )

    assert summarize_signal_cli_error(stderr) == "signal-cli: error: unrecognized arguments: --bad"


def test_summarize_signal_cli_error_prefers_failed_message() -> None:
    stderr = "\n".join(
        [
            "usage: signal-cli [-h] [--version]",
            "Failed to read local accounts list",
        ]
    )

    assert summarize_signal_cli_error(stderr) == "Failed to read local accounts list"


def test_parse_signal_linked_numbers_reads_number_lines() -> None:
    output = """
    INFO  AccountHelper - The Signal protocol expects regular receives.
    Number: +4916096508449
    """

    assert parse_signal_linked_numbers(output) == ("+4916096508449",)


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


def test_parse_signal_json_output_accepts_multiple_json_documents() -> None:
    output = '{"envelope": {"sourceNumber": "+49123"}}\n{"receipt": {"when": 1}}\n'

    assert parse_signal_json_output(output) == (
        {"envelope": {"sourceNumber": "+49123"}},
        {"receipt": {"when": 1}},
    )


def test_parse_signal_json_prefix_returns_remainder() -> None:
    events, remainder = parse_signal_json_prefix(
        '{"envelope": {"sourceNumber": "+49123"}}\n{"receipt":'
    )

    assert events == ({"envelope": {"sourceNumber": "+49123"}},)
    assert remainder == '{"receipt":'


def test_render_terminal_qr_uses_python_qrcode() -> None:
    rendered = render_terminal_qr("sgnl://linkdevice?uuid=abc")

    assert rendered is not None
    assert "\n" in rendered
    assert "\033[" in rendered


def test_normalize_whatsapp_event() -> None:
    message = normalize_baileys_event(
        {
            "key": {"remoteJid": "chat@g.us", "participant": "sender@s.whatsapp.net", "id": "abc"},
            "messageTimestamp": 1781164800,
            "message": {"conversation": "hello"},
        }
    )

    assert message is not None
    assert message.source == Source.WHATSAPP
    assert message.text == "hello"
    assert message.is_group_chat


def test_normalize_whatsapp_direct_event() -> None:
    message = normalize_baileys_event(
        {
            "key": {"remoteJid": "sender@s.whatsapp.net", "id": "abc"},
            "messageTimestamp": 1781164800,
            "pushName": "Sender",
            "message": {"conversation": "hello direct"},
        }
    )

    assert message is not None
    assert not message.is_group_chat
    assert message.chat_name is None
    assert message.sender_name == "Sender"


def test_normalize_whatsapp_image_attachment() -> None:
    message = normalize_baileys_event(
        {
            "key": {"remoteJid": "sender@s.whatsapp.net", "id": "abc"},
            "messageTimestamp": 1781164800,
            "message": {"imageMessage": {"caption": "photo"}},
            "attachments": [
                {
                    "contentType": "image/jpeg",
                    "filename": "abc.jpg",
                    "localPath": "/tmp/post-office/abc.jpg",
                    "sizeBytes": 123,
                    "sourceId": "abc",
                }
            ],
        }
    )

    assert message is not None
    assert message.text == "photo"
    assert len(message.attachments) == 1
    assert message.attachments[0].content_type == "image/jpeg"
    assert str(message.attachments[0].local_path) == "/tmp/post-office/abc.jpg"


def test_normalize_signal_event() -> None:
    message = normalize_signal_event(
        {
            "envelope": {
                "sourceNumber": "+49123",
                "timestamp": 1781164800000,
                "dataMessage": {"message": "hello signal", "timestamp": 1781164800000},
            }
        }
    )

    assert message is not None
    assert message.source == Source.SIGNAL
    assert message.text == "hello signal"
    assert not message.is_group_chat


def test_normalize_signal_group_event() -> None:
    message = normalize_signal_event(
        {
            "envelope": {
                "sourceNumber": "+49123",
                "timestamp": 1781164800000,
                "dataMessage": {
                    "message": "hello group",
                    "timestamp": 1781164800000,
                    "groupInfo": {"groupId": "group-1", "groupName": "Signal Group"},
                },
            },
        }
    )

    assert message is not None
    assert message.is_group_chat
    assert message.chat_id == "group-1"
    assert message.chat_name == "Signal Group"


def test_normalize_signal_attachment_metadata() -> None:
    message = normalize_signal_event(
        {
            "envelope": {
                "sourceNumber": "+49123",
                "dataMessage": {
                    "message": "photo",
                    "attachments": [
                        {
                            "contentType": "image/png",
                            "filename": "signal.png",
                            "path": "/tmp/post-office/signal.png",
                        }
                    ],
                },
            }
        }
    )

    assert message is not None
    assert len(message.attachments) == 1
    assert message.attachments[0].filename == "signal.png"


def test_normalize_signal_copies_downloaded_attachment(tmp_path) -> None:
    downloaded = tmp_path / "signal-cli-attachment"
    downloaded.write_bytes(b"image-bytes")
    media_dir = tmp_path / "media"

    message = normalize_signal_event(
        {
            "envelope": {
                "sourceNumber": "+49123",
                "timestamp": 1781164800000,
                "dataMessage": {
                    "message": "photo",
                    "timestamp": 1781164800000,
                    "attachments": [
                        {
                            "contentType": "image/jpeg",
                            "storedFilename": str(downloaded),
                            "id": "attachment-1",
                            "size": 11,
                        }
                    ],
                },
            }
        },
        media_dir=media_dir,
    )

    assert message is not None
    assert len(message.attachments) == 1
    attachment = message.attachments[0]
    assert attachment.local_path is not None
    assert attachment.local_path.parent == media_dir / "49123" / "1781164800000"
    assert attachment.local_path.suffix == ".jpg"
    assert attachment.local_path.read_bytes() == b"image-bytes"


def test_normalize_signal_copies_bare_attachment_path(tmp_path) -> None:
    downloaded = tmp_path / "signal-cli-attachment"
    downloaded.write_bytes(b"image-bytes")
    media_dir = tmp_path / "media"

    message = normalize_signal_event(
        {
            "envelope": {
                "sourceNumber": "+49123",
                "timestamp": 1781164800000,
                "dataMessage": {
                    "timestamp": 1781164800000,
                    "attachments": [str(downloaded)],
                },
            }
        },
        media_dir=media_dir,
    )

    assert message is not None
    assert len(message.attachments) == 1
    attachment = message.attachments[0]
    assert attachment.local_path is not None
    assert attachment.local_path.parent == media_dir / "49123" / "1781164800000"
    assert attachment.local_path.read_bytes() == b"image-bytes"


def test_normalize_signal_edit_message() -> None:
    message = normalize_signal_event(
        {
            "envelope": {
                "sourceNumber": "+49123",
                "timestamp": 1781164800000,
                "editMessage": {
                    "targetSentTimestamp": 1781164799000,
                    "dataMessage": {
                        "message": "edited signal",
                        "timestamp": 1781164800000,
                    },
                },
            },
        }
    )

    assert message is not None
    assert message.source == Source.SIGNAL
    assert message.text == "edited signal"


def test_normalize_signal_sync_sent_message() -> None:
    message = normalize_signal_event(
        {
            "envelope": {
                "sourceNumber": "+49123",
                "timestamp": 1781164800000,
                "syncMessage": {
                    "sentMessage": {
                        "destination": "+49456",
                        "timestamp": 1781164800000,
                        "message": "hello from sync",
                    }
                },
            }
        },
        include_own_messages=True,
    )

    assert message is not None
    assert message.source == Source.SIGNAL
    assert message.chat_id == "+49456"
    assert message.text == "hello from sync"


def test_normalize_signal_sync_sent_message_with_nested_data_message() -> None:
    message = normalize_signal_event(
        {
            "envelope": {
                "sourceNumber": "+49123",
                "timestamp": 1781164800000,
                "syncMessage": {
                    "sentMessage": {
                        "destinationNumber": "+49456",
                        "dataMessage": {
                            "timestamp": 1781164800000,
                            "message": "hello nested sync",
                        },
                    }
                },
            },
        },
        include_own_messages=True,
    )

    assert message is not None
    assert message.source == Source.SIGNAL
    assert message.chat_id == "+49456"
    assert message.text == "hello nested sync"


def test_normalize_signal_ignores_sync_sent_message_by_default() -> None:
    message = normalize_signal_event(
        {
            "envelope": {
                "sourceNumber": "+49123",
                "syncMessage": {
                    "sentMessage": {
                        "destination": "+49456",
                        "timestamp": 1781164800000,
                        "message": "own message",
                    }
                },
            }
        }
    )

    assert message is None


def test_signal_event_kind_describes_ignored_events() -> None:
    assert signal_event_kind({"exception": {"type": "InvalidMessageException"}}) == (
        "exception.InvalidMessageException"
    )
    assert signal_event_kind({"envelope": {"editMessage": {}}}) == "editMessage"
    assert signal_event_kind({"envelope": {"receiptMessage": {}}}) == "receiptMessage"
    assert (
        signal_event_kind({"envelope": {"syncMessage": {"readMessages": []}}})
        == "syncMessage.readMessages"
    )


def test_signal_event_summary_logs_keys_not_values() -> None:
    summary = signal_event_summary(
        {
            "envelope": {
                "sourceNumber": "+49456",
                "unknownMessage": {"secret": "message text"},
            },
        }
    )

    assert summary == "top=('envelope',) envelope=('sourceNumber', 'unknownMessage')"
    assert "+49123" not in summary
    assert "message text" not in summary
