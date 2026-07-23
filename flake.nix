{
  description = "Stikka-NG development shell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f system);
    in {
      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          buildFirmwareCmd = pkgs.writeShellScriptBin "build-firmware" ''
            set -euo pipefail
            repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
            exec "$repo_root/scripts/build-firmware.sh" "$@"
          '';
        in {
          default = pkgs.mkShell {
            packages = with pkgs; [
              git
              nodejs_22
              python312
              uv
              platformio
              openssl
              pkg-config
              jq
              buildFirmwareCmd
            ];

            shellHook = ''
              unset PIP_USER
              unset PIP_TARGET

              echo "Stikka-NG dev shell ready"
              echo "- Python: $(python --version 2>/dev/null || true)"
              echo "- Node:   $(node --version 2>/dev/null || true)"
              echo "- npm:    $(npm --version 2>/dev/null || true)"
              echo "- uv:     $(uv --version 2>/dev/null || true)"
              echo "- pio:    $(pio --version 2>/dev/null || true)"
              echo "- command: build-firmware"
              echo "- Open project ESP firmware in ./esp32 with PlatformIO extension"
            '';
          };
        });
    };
}
