# Post Office

Post Office runs on NixOS, collects Signal and WhatsApp messages, filters them with a ban-list, and prints allowed messages live on a CPCL-compatible thermal printer.

## NixOS Setup

Import the module from the flake and configure it from your NixOS configuration:

```nix
{
  inputs.post-office.url = "path:/home/salomon/repos/post-office";

  outputs = { self, nixpkgs, post-office, ... }: {
    nixosConfigurations.pi = nixpkgs.lib.nixosSystem {
      system = "aarch64-linux";
      modules = [
        post-office.nixosModules.default
        {
          services.post-office = {
            enable = true;

            printer.bluetoothAddress = "00:11:22:33:44:55";
            printer.bluetoothChannel = 1;

            banlist.senderIds = [
              # { source = "signal"; id = "+49123456789"; reason = "example"; }
            ];
            banlist.chatIds = [
              # { source = "whatsapp"; id = "12345@g.us"; reason = "example"; }
            ];
          };
        }
      ];
    };
  };
}
```

Then switch the system:

```sh
sudo nixos-rebuild switch --flake .#hostname
```

## Printer

When `services.post-office.printer.bluetoothAddress` is set, the module enables Bluetooth and creates `post-office-rfcomm.service`, which binds the printer to `/dev/rfcomm0` before Post Office starts.

Check it with:

```sh
systemctl status post-office-rfcomm.service
ls -l /dev/rfcomm0
```

If your printer uses a different RFCOMM channel, set:

```nix
services.post-office.printer.bluetoothChannel = 2;
```

## Linking

On first start, Post Office links Signal and WhatsApp as secondary devices and prints QR codes in the service log.

```sh
journalctl -u post-office.service -f
```

Scan the Signal QR code from Signal on your phone. Scan the WhatsApp QR code from WhatsApp linked devices.

Mutable state lives in `/var/lib/post-office`, including:

- `post-office.sqlite3`
- `signal-cli/`
- `whatsapp-auth/`
- `media/`

## Service

Useful service commands:

```sh
systemctl status post-office.service
journalctl -u post-office.service -f
sudo systemctl restart post-office.service
```

## Disclaimer

Post Office is an unofficial project and is not affiliated with Signal, WhatsApp, or Meta. It uses community tooling to receive messages, so upstream service changes may break integrations.

## License

MIT
