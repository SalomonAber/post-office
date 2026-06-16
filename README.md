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
post-office --config config.toml check-signal
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

## Signal setup

`signal-cli` needs mutable local account state before Post Office can receive messages. For a Raspberry Pi service, prefer linking the Pi as a secondary device instead of registering the phone number as the primary device:

```sh
signal-cli link -n post-office
```

Scan the printed `sgnl://linkdevice?...` URI from Signal on your phone. Then verify that the account is visible locally:

```sh
signal-cli listAccounts
nix run .# -- --config config.toml check-signal
```

Only after `check-signal` succeeds should you run:

```sh
nix run .# -- --config config.toml daemon
```

Linked devices only receive messages that arrive after the link is established. If the daemon logs `signal-cli receive completed events=0 messages=0`, send a fresh message from another Signal account while the daemon is running. You can also test the raw receive path directly:

```sh
signal-cli -a PHONE -o json receive --timeout 10
```

If `signal-cli receive` repeatedly fails with a Java `NullPointerException` while retrying failed received messages, Post Office treats it as a transient upstream `signal-cli` failure and retries with bounded exponential backoff. This usually indicates a bad cached retry envelope in `signal-cli` state; upgrading `signal-cli` or relinking the device may be required if it persists.

If you intentionally want this machine to be the primary Signal device, use `signal-cli -a PHONE register`, then `signal-cli -a PHONE verify CODE` instead. The linked-device flow is usually safer for this project.

## Current CLI commands

- `init-db`: create or migrate the SQLite database.
- `validate-config`: validate the TOML configuration.
- `check-signal`: verify that the configured Signal account is locally registered or linked.
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
