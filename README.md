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
post-office --config config.toml print-pending
pytest
```

## Current CLI commands

- `init-db`: create or migrate the SQLite database.
- `validate-config`: validate the TOML configuration.
- `ingest-fixture SOURCE PATH`: normalize and store one fixture event for `signal`, `whatsapp`, or `instagram`.
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

1. Implement the real `signal-cli` receive loop first; it has the least cross-runtime complexity.
2. Add the long-running daemon command that supervises enabled source adapters and calls the ingestion/live-printer services.
3. Add NixOS service wiring for the daemon, plus the existing daily-report timer.
4. Replace fixture-only source tests with recorded integration fixtures from real `signal-cli`, Baileys, and `instagrapi` payloads.
5. Validate on Raspberry Pi with the real ESC/POS printer.
