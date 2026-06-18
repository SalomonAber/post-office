from datetime import UTC, datetime

from post_office.cli import main
from post_office.db import Database
from post_office.models import Message, Source


def test_print_pending_prints_failed_message_error(tmp_path, capsys) -> None:
    state_dir = tmp_path / "state"
    config_path = tmp_path / "config.toml"
    missing_device = tmp_path / "missing-rfcomm0"
    config_path.write_text(
        f"""
        [app]
        state_dir = "{state_dir}"

        [printer]
        enabled = true
        device_path = "{missing_device}"
        """
    )
    database = Database(state_dir / "post-office.sqlite3")
    database.migrate()
    database.insert_message(
        Message(
            source=Source.SIGNAL,
            chat_id="chat",
            sender_id="sender",
            source_message_id="source-id",
            timestamp=datetime(2026, 6, 11, tzinfo=UTC),
            text="hello",
        )
    )

    exit_code = main(["--config", str(config_path), "print-pending"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "delivered=0 filtered=0 failed=1" in output
    assert "failed message_id=" in output
    assert f"printer device does not exist: {missing_device}" in output
