{ self ? null }:

{ config, lib, pkgs, ... }:

let
  cfg = config.services.post-office;
  toml = pkgs.formats.toml { };

  ruleType = lib.types.submodule {
    options = {
      source = lib.mkOption {
        type = lib.types.enum [ "signal" "whatsapp" ];
        description = "Message source for this ban-list rule.";
      };
      id = lib.mkOption {
        type = lib.types.str;
        description = "Sender or chat ID to ban.";
      };
      reason = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "Optional note explaining why this rule exists.";
      };
      enabled = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Whether this rule is active.";
      };
    };
  };

  renderRule = rule:
    {
      inherit (rule) source id enabled;
    } // lib.optionalAttrs (rule.reason != null) {
      inherit (rule) reason;
    };

  generatedConfig = toml.generate "post-office.toml" {
    app = {
      inherit (cfg) timezone;
      state_dir = cfg.stateDir;
    };

    banlist = {
      sender_ids = map renderRule cfg.banlist.senderIds;
      chat_ids = map renderRule cfg.banlist.chatIds;
    };

    printer = {
      enabled = cfg.printer.enable;
      device_path = cfg.printer.devicePath;
      width_chars = cfg.printer.widthChars;
    };

    sources = {
      signal = {
        enabled = cfg.signal.enable;
        data_dir = "${cfg.stateDir}/signal-cli";
        media_dir = "${cfg.stateDir}/media/signal";
        include_own_messages = cfg.signal.includeOwnMessages;
        ignore_muted_chats = cfg.signal.ignoreMutedChats;
        restart_delay_seconds = cfg.signal.restartDelaySeconds;
        max_restart_delay_seconds = cfg.signal.maxRestartDelaySeconds;
      };

      whatsapp = {
        enabled = cfg.whatsapp.enable;
        auth_dir = "${cfg.stateDir}/whatsapp-auth";
        media_dir = "${cfg.stateDir}/media/whatsapp";
        include_own_messages = cfg.whatsapp.includeOwnMessages;
        ignore_muted_chats = cfg.whatsapp.ignoreMutedChats;
        restart_delay_seconds = cfg.whatsapp.restartDelaySeconds;
        max_restart_delay_seconds = cfg.whatsapp.maxRestartDelaySeconds;
      };
    };
  };

  configFile = if cfg.configFile == null then generatedConfig else cfg.configFile;
  rfcommService = "post-office-rfcomm.service";
  rfcommEnabled = cfg.printer.enable && cfg.printer.bluetoothAddress != null;
  defaultPackage =
    if self == null then
      null
    else
      self.packages.${pkgs.stdenv.hostPlatform.system}.default;
in
{
  options.services.post-office = {
    enable = lib.mkEnableOption "Post Office message collector";

    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = defaultPackage;
      defaultText = lib.literalExpression "self.packages.\${pkgs.stdenv.hostPlatform.system}.default";
      description = "Post Office package to run.";
    };

    configFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = ''
        Optional path to a Post Office TOML configuration file.

        When unset, the module generates a configuration
        from the NixOS options below.
      '';
    };

    stateDir = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/post-office";
      description = "Directory for the SQLite database, Signal state, WhatsApp auth, and media.";
    };

    user = lib.mkOption {
      type = lib.types.str;
      default = "post-office";
      description = "User that runs the Post Office daemon.";
    };

    group = lib.mkOption {
      type = lib.types.str;
      default = "post-office";
      description = "Primary group for the Post Office daemon.";
    };

    timezone = lib.mkOption {
      type = lib.types.str;
      default =
        if (config.time.timeZone or null) != null then
          config.time.timeZone
        else
          "Europe/Zurich";
      description = "Timezone written to the generated Post Office configuration.";
    };

    restartSec = lib.mkOption {
      type = lib.types.str;
      default = "10s";
      description = "systemd restart delay for the daemon.";
    };

    printer = {
      enable = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Whether to write live messages to the thermal printer.";
      };
      devicePath = lib.mkOption {
        type = lib.types.str;
        default = "/dev/rfcomm0";
        description = "Bluetooth serial device path for the CPCL printer.";
      };
      widthChars = lib.mkOption {
        type = lib.types.ints.positive;
        default = 72;
        description = "Receipt text width in characters.";
      };
      bluetoothAddress = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        example = "00:11:22:33:44:55";
        description = ''
          Bluetooth MAC address of the printer.

          When set, the module binds printer.devicePath with rfcomm before
          starting Post Office. Leave unset if another service or manual setup
          creates the rfcomm device.
        '';
      };
      bluetoothChannel = lib.mkOption {
        type = lib.types.ints.positive;
        default = 1;
        description = "Bluetooth RFCOMM channel used by the printer.";
      };
    };

    signal = {
      enable = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Enable Signal collection through signal-cli.";
      };
      includeOwnMessages = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = "Print Signal messages sent by the linked account.";
      };
      ignoreMutedChats = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Ignore Signal messages from muted direct chats and group chats.";
      };
      restartDelaySeconds = lib.mkOption {
        type = lib.types.ints.positive;
        default = 5;
        description = "Initial Signal receive retry delay.";
      };
      maxRestartDelaySeconds = lib.mkOption {
        type = lib.types.ints.positive;
        default = 300;
        description = "Maximum Signal receive retry delay.";
      };
    };

    whatsapp = {
      enable = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Enable WhatsApp collection through the Baileys bridge.";
      };
      includeOwnMessages = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = "Print WhatsApp messages sent by the linked account.";
      };
      ignoreMutedChats = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Ignore WhatsApp messages from muted chats.";
      };
      restartDelaySeconds = lib.mkOption {
        type = lib.types.ints.positive;
        default = 5;
        description = "Initial WhatsApp bridge retry delay.";
      };
      maxRestartDelaySeconds = lib.mkOption {
        type = lib.types.ints.positive;
        default = 300;
        description = "Maximum WhatsApp bridge retry delay.";
      };
    };

    banlist = {
      senderIds = lib.mkOption {
        type = lib.types.listOf ruleType;
        default = [ ];
        description = "Sender IDs to filter before printing.";
      };
      chatIds = lib.mkOption {
        type = lib.types.listOf ruleType;
        default = [ ];
        description = "Chat IDs to filter before printing.";
      };
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.package != null;
        message = "services.post-office.package must be set when the module is not imported from the Post Office flake.";
      }
    ];

    hardware.bluetooth.enable = lib.mkIf rfcommEnabled true;

    services.udev.extraRules = ''
      KERNEL=="rfcomm[0-9]*", GROUP="${cfg.group}", MODE="0660"
    '';

    users.groups.${cfg.group} = { };
    users.users.${cfg.user} = {
      isSystemUser = true;
      group = cfg.group;
      home = cfg.stateDir;
    };

    systemd.tmpfiles.rules = lib.mkIf (cfg.stateDir != "/var/lib/post-office") [
      "d ${cfg.stateDir} 0750 ${cfg.user} ${cfg.group} -"
    ];

    systemd.services.post-office-rfcomm = lib.mkIf rfcommEnabled {
      description = "Bind Post Office Bluetooth printer RFCOMM device";
      after = [ "bluetooth.service" ];
      wants = [ "bluetooth.service" ];
      wantedBy = [ "multi-user.target" ];

      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = "${pkgs.bluez}/bin/rfcomm bind ${cfg.printer.devicePath} ${cfg.printer.bluetoothAddress} ${toString cfg.printer.bluetoothChannel}";
        ExecStop = "${pkgs.bluez}/bin/rfcomm release ${cfg.printer.devicePath}";
      };
    };

    systemd.services.post-office = {
      description = "Post Office message ingestion daemon";
      after = [ "network-online.target" ]
        ++ lib.optional rfcommEnabled rfcommService;
      wants = [ "network-online.target" ]
        ++ lib.optional rfcommEnabled rfcommService;
      wantedBy = [ "multi-user.target" ];

      serviceConfig = {
        Type = "simple";
        User = cfg.user;
        Restart = "on-failure";
        RestartSec = cfg.restartSec;
      } // lib.optionalAttrs (cfg.package != null) {
        ExecStart = "${cfg.package}/bin/post-office --config ${configFile} daemon";
      } // lib.optionalAttrs (cfg.stateDir == "/var/lib/post-office") {
        StateDirectory = "post-office";
        StateDirectoryMode = "0750";
      };
    };
  };
}
