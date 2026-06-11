{
  description = "Post Office message collector";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          python = pkgs.python311;
        in
        {
          default = python.pkgs.buildPythonApplication {
            pname = "post-office";
            version = "0.1.0";
            src = ./.;
            pyproject = true;
            build-system = [ python.pkgs.hatchling ];
            dependencies = [ ];
            nativeCheckInputs = [ python.pkgs.pytest ];
            checkPhase = "pytest";
          };
        });

      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.python311
              pkgs.python311Packages.pytest
              pkgs.python311Packages.ruff
              pkgs.python311Packages.mypy
              pkgs.nodejs_22
              pkgs.signal-cli
              pkgs.sqlite
            ];
          };
        });
    };
}
