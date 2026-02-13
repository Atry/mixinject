{ ... }:
{
  imports = [
    ./dev.nix
  ];
  partitions.dev.module.perSystem =
    { pkgs
    , config
    , lib
    , ...
    }:
    let
      overlay-dev-env = config.packages.overlay-dev-env;
      start-jupyter-lab = pkgs.writeShellApplication {
        name = "start-jupyter-lab";
        runtimeInputs = [
          overlay-dev-env
          pkgs.screen
          pkgs.coreutils
          pkgs.xxd
        ];
        text = ''
          exec screen -L -Logfile '%S.%n.local.screenlog' -d -m -S "jupyter-''${PWD##*/}" jupyter lab --port "$JUPYTER_PORT" --IdentityProvider.token "$JUPYTER_TOKEN" --ip localhost --no-browser --ServerApp.port_retries=0
        '';
      };
    in
    {
      ml-ops.devcontainer.devenvShellModule = {
        packages = [
          start-jupyter-lab
          pkgs.xxd
        ];
        enterShell = ''
          PWD_HASH=$(echo -n "$PWD" | sha256sum | cut -c1-8)
          JUPYTER_PORT=$((16#$PWD_HASH % 1000 + 11000))
          JUPYTER_URL="http://localhost:$JUPYTER_PORT"
          export JUPYTER_PORT
          export JUPYTER_URL

          if [ -z "''${JUPYTER_TOKEN:-}" ]; then
            echo "JUPYTER_TOKEN not found, generating a new one..." >&2
            JUPYTER_TOKEN=$(xxd -c 32 -l 32 -p /dev/urandom)
            export JUPYTER_TOKEN
            touch .env
            echo "JUPYTER_TOKEN=$JUPYTER_TOKEN" >> .env
            echo "Generated and saved JUPYTER_TOKEN to .env"
          fi
        '';
      };
    };
}
