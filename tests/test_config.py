from post_office.config import load_config


def test_load_whatsapp_config(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [sources.whatsapp]
        enabled = true
        auth_dir = "/var/lib/post-office/whatsapp/auth"
        include_own_messages = true
        restart_delay_seconds = 7
        max_restart_delay_seconds = 90
        """
    )

    config = load_config(config_path)

    assert config.sources.whatsapp.enabled
    assert str(config.sources.whatsapp.auth_dir) == "/var/lib/post-office/whatsapp/auth"
    assert config.sources.whatsapp.include_own_messages
    assert config.sources.whatsapp.restart_delay_seconds == 7
    assert config.sources.whatsapp.max_restart_delay_seconds == 90


def test_load_signal_config(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [sources.signal]
        enabled = true
        data_dir = "/var/lib/post-office/signal"
        media_dir = "/var/lib/post-office/media/signal"
        include_own_messages = true
        restart_delay_seconds = 7
        max_restart_delay_seconds = 90
        """
    )

    config = load_config(config_path)

    assert config.sources.signal.enabled
    assert str(config.sources.signal.data_dir) == "/var/lib/post-office/signal"
    assert str(config.sources.signal.media_dir) == "/var/lib/post-office/media/signal"
    assert config.sources.signal.include_own_messages
    assert config.sources.signal.restart_delay_seconds == 7
    assert config.sources.signal.max_restart_delay_seconds == 90


def test_load_printer_config(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [printer]
        enabled = true
        device_path = "/dev/rfcomm0"
        width_chars = 32
        """
    )

    config = load_config(config_path)

    assert config.printer.enabled
    assert str(config.printer.device_path) == "/dev/rfcomm0"
    assert config.printer.width_chars == 32


def test_load_media_dirs_from_state_dir(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [app]
        state_dir = "/var/lib/post-office"
        """
    )

    config = load_config(config_path)

    assert str(config.database_path) == "/var/lib/post-office/post-office.sqlite3"
    assert str(config.sources.whatsapp.media_dir) == "/var/lib/post-office/media/whatsapp"
    assert str(config.sources.signal.data_dir) == "/var/lib/post-office/signal-cli"
    assert str(config.sources.signal.media_dir) == "/var/lib/post-office/media/signal"
