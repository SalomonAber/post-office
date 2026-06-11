{ config, lib, pkgs, ... }:

let
  cfg = config.services.post-office;
in
{
  options.services.post-office = {
    enable = lib.mkEnableOption "Post Office message collector";
    package = lib.mkOption {
      type = lib.types.package;
      description = "Post Office package to run.";
    };
    configFile = lib.mkOption {
      type = lib.types.path;
      description = "Path to the Post Office TOML configuration file.";
    };
    stateDir = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/post-office";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.post-office-init-db = {
      description = "Initialize Post Office database";
      serviceConfig = {
        Type = "oneshot";
        StateDirectory = "post-office";
        ExecStart = "${cfg.package}/bin/post-office --config ${cfg.configFile} init-db";
      };
    };

    systemd.services.post-office-daily-report = {
      description = "Send Post Office daily report";
      after = [ "network-online.target" "post-office-init-db.service" ];
      wants = [ "network-online.target" ];
      serviceConfig = {
        Type = "oneshot";
        StateDirectory = "post-office";
        ExecStart = "${cfg.package}/bin/post-office --config ${cfg.configFile} daily-report";
      };
    };

    systemd.timers.post-office-daily-report = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = "daily";
        Persistent = true;
      };
    };
  };
}
