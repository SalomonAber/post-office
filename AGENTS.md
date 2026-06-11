# Post Office

Post office is an application that collects my messages from various sources, filters them and creates a report.

## Sources

The following sources will be collected:

 - Signal messages (signal-cli)
 - Whatsapp messages (baileys)
 - Instagram messages (instagrapi)

## Filters

For now there will be a user maintained ban-list.

## Output

There will be two two initial report types:

 1. Daily report: Messages are conglomerated into a daily report and sent per email.
 2. Live report: Every message will be sent to a thermal printer as it is received.

## Technical Details

Post office is a nix package which runs on a Raspberry Pi 4.
