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
pytest
```

## Runtime model

The Python app is the stable core. Each source adapter normalizes upstream events into the canonical `Message` model before storage. Outputs only consume normalized messages, so source-specific fragility stays isolated.

## Mutable state

For Nix/NixOS deployment, keep mutable state outside the Nix store, usually under:

- `/var/lib/post-office/post-office.sqlite3`
- `/var/lib/post-office/signal/`
- `/var/lib/post-office/whatsapp/`
- `/var/lib/post-office/instagram/`

## Next implementation work

1. Replace source stubs with real event loops.
2. Add NixOS module service/timer wiring.
3. Add fixture-based source integration tests.
4. Validate on Raspberry Pi with the real ESC/POS printer.
