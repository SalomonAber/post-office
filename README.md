# Post Office

Post Office collects messages from Signal, WhatsApp, and Instagram, filters them with a user-maintained ban-list, and sends either a daily email report or live thermal-printer output.

## Current implementation status

This repository contains the initial scaffold and core implementation:

- Python orchestration core
- SQLite persistence
- TOML configuration
- sender/chat ban-list filtering
- daily SMTP report rendering/sending
- ESC/POS USB printer adapter with dry-run fallback
- ingestion and live-printer runtime services with delivery logging
- source adapter interfaces and initial stubs for `signal-cli`, Baileys bridge, and `instagrapi`
- small Node.js WhatsApp bridge scaffold
- Nix flake/dev shell scaffold

## Quick start

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cp config.example.toml config.toml
post-office --config config.toml init-db
post-office --config config.toml validate-config
post-office --config config.toml daemon
post-office --config config.toml print-pending
pytest
```

With Nix, the app package wraps runtime tools such as `signal-cli` and `node`, so `nix run . -- --config config.toml daemon` can find them without entering a shell.

For day-to-day development, `direnv` is optional but convenient:

```sh
direnv allow
```

The checked-in `.envrc` uses the flake dev shell, which provides Python, pytest, Ruff, mypy, Node.js, `signal-cli`, and SQLite.

The Signal adapter calls `signal-cli -a ACCOUNT -o json receive --timeout SECONDS`; `-o json` is a global `signal-cli` option and must appear before the `receive` subcommand.

## Current CLI commands

- `init-db`: create or migrate the SQLite database.
- `validate-config`: validate the TOML configuration.
- `ingest-fixture SOURCE PATH`: normalize and store one fixture event for `signal`, `whatsapp`, or `instagram`.
- `daemon`: run enabled source adapters continuously and process incoming messages through the ingestion/live-printer pipeline.
- `print-pending`: print stored messages that have not yet been delivered to the live printer target.
- `daily-report`: render and optionally send the last 24 hours of allowed messages by SMTP.

## Runtime model

The Python app is the stable core. Each source adapter normalizes upstream events into the canonical `Message` model before storage. Outputs only consume normalized messages, so source-specific fragility stays isolated.

## Mutable state

For Nix/NixOS deployment, keep mutable state outside the Nix store, usually under:

- `/var/lib/post-office/post-office.sqlite3`
- `/var/lib/post-office/signal/`
- `/var/lib/post-office/whatsapp/`
- `/var/lib/post-office/instagram/`

## Next implementation work

1. Test the `signal-cli` receive loop with a real linked Signal account.
2. Add recorded integration fixtures from real `signal-cli`, Baileys, and `instagrapi` payloads.
3. Harden the WhatsApp bridge supervision and QR pairing flow.
4. Implement conservative Instagram polling with persisted cursors.
5. Validate on Raspberry Pi with the real ESC/POS printer.
