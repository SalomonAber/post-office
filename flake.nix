{
  description = "Post Office message collector";

  inputs = {
    # Temporary until https://github.com/NixOS/nixpkgs/pull/530853 is merged.
    nixpkgs.url = "github:NixOS/nixpkgs/pull/530853/head";
  };

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      signalCliOverlay = final: prev:
        let
          libsignal-jni = final.rustPlatform.buildRustPackage {
            pname = "libsignal-jni";
            version = "0.94.4";

            src = final.fetchFromGitHub {
              owner = "signalapp";
              repo = "libsignal";
              tag = "v0.94.4";
              hash = "sha256-Uh/j8cXUWgWgSo9UBfYOFuC8i+2YdMwGHcXf55PkGgU=";
            };

            cargoHash = "sha256-st6zTKvxSsyMce22E8nFsJMGjQkk9sEAzSCmyZP8x20=";

            nativeBuildInputs = [
              final.cmake
              final.pkg-config
              final.protobuf
              final.perl
              final.openjdk25_headless
              final.gitMinimal
            ];

            LIBCLANG_PATH = "${final.llvmPackages.libclang.lib}/lib";
            BINDGEN_EXTRA_CLANG_ARGS =
              if final.stdenv.hostPlatform.isDarwin then
                "-isystem ${final.llvmPackages.libclang.lib}/lib/clang/${final.lib.versions.major final.llvmPackages.libclang.version}/include"
              else
                "-isystem ${final.stdenv.cc.libc.dev}/include -isystem ${final.llvmPackages.libclang.lib}/lib/clang/${final.lib.versions.major final.llvmPackages.libclang.version}/include";

            buildAndTestSubdir = "rust/bridge/jni";
            cargoBuildFlags = [ "-p" "libsignal-jni" ];
            RUSTFLAGS = "--cfg aes_armv8 --cfg tokio_unstable";

            env.BORING_BSSL_SOURCE_EXTERNAL = "0";

            installPhase = ''
              runHook preInstall
              mkdir -p $out/lib
              find target -name "libsignal_jni${final.stdenv.hostPlatform.extensions.sharedLibrary}" | head -1 | while read f; do
                install -Dm755 "$f" "$out/lib/$(basename "$f")"
              done
              runHook postInstall
            '';
          };
        in
        {
          signal-cli = prev.signal-cli.overrideAttrs (old: {
            postInstall = (old.postInstall or "") + ''
              cp -f ${libsignal-jni}/lib/* $out/lib/
            '';
          });
        };
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; overlays = [ signalCliOverlay ]; };
          python = pkgs.python311;
          whatsappBridge = pkgs.buildNpmPackage {
            pname = "post-office-whatsapp-bridge";
            version = "0.1.0";
            src = ./bridges/whatsapp;
            npmDepsHash = "sha256-T/1dx2OoI6XrhhqkaVa7utiwUaB4Q8OJF4Wd+z6/OUE=";
            dontNpmBuild = true;
            makeCacheWritable = true;
            installPhase = ''
              runHook preInstall
              mkdir -p $out/libexec/post-office/bridges/whatsapp
              cp -R index.js package.json package-lock.json node_modules \
                $out/libexec/post-office/bridges/whatsapp/
              runHook postInstall
            '';
          };
        in
        {
          default = python.pkgs.buildPythonApplication {
            pname = "post-office";
            version = "0.1.0";
            src = ./.;
            pyproject = true;
            build-system = [ python.pkgs.hatchling ];
            dependencies = [ python.pkgs.pyqrcode python.pkgs.pillow ];
            nativeBuildInputs = [ pkgs.makeWrapper ];
            nativeCheckInputs = [ python.pkgs.pytest ];
            checkPhase = "pytest";
            postInstall = ''
              wrapProgram $out/bin/post-office \
                --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.signal-cli pkgs.nodejs_22 ]} \
                --set POST_OFFICE_WHATSAPP_BRIDGE_PATH ${whatsappBridge}/libexec/post-office/bridges/whatsapp/index.js
            '';
          };
          whatsapp-bridge = whatsappBridge;
        });

      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; overlays = [ signalCliOverlay ]; };
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.python311
              pkgs.python311Packages.pytest
              pkgs.python311Packages.ruff
              pkgs.python311Packages.mypy
              pkgs.python311Packages.pillow
              pkgs.python311Packages.pyqrcode
              pkgs.nodejs_22
              pkgs.signal-cli
              pkgs.sqlite
            ];
          };
        });

      nixosModules.default = import ./nix/module.nix { inherit self; };
      nixosModules.post-office = self.nixosModules.default;
    };
}
