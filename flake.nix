{
  nixConfig = {
    extra-substituters = [
      "https://cache.nixos.org"
      "https://devenv.cachix.org"
      "https://nix-community.cachix.org"
      "https://install.determinate.systems"
      "https://cache.nixos-cuda.org"

    ];
    extra-trusted-substituters = [
      "https://cache.nixos.org"
      "https://devenv.cachix.org"
      "https://nix-community.cachix.org"
      "https://install.determinate.systems"
      "https://cache.nixos-cuda.org"
    ];
    extra-trusted-public-keys = [
      "cache.flakehub.com-3:hJuILl5sVK4iKm86JzgdXW12Y2Hwd5G07qKtHTOcDCM="
      "cache.nixos-cuda.org:74DUi4Ye579gUqzH4ziL9IyiJBlDpMRn9MBN8oNan9M="
    ];
  };
  inputs = {
    systems.url = "github:nix-systems/default";
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts = {
      url = "github:hercules-ci/flake-parts";
      inputs.nixpkgs-lib.follows = "nixpkgs";
    };
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix_hammer_overrides = {
      url = "github:TyberiusPrime/uv2nix_hammer_overrides";
      inputs.nixpkgs.follows = "nixpkgs";
    };

  };
  outputs =
    inputs:
    inputs.flake-parts.lib.mkFlake { inherit inputs; } (
      { lib, ... }:
      {
        systems = import inputs.systems;
        perSystem =
          perSystem@{
            pkgs,
            system,
            inputs',
            ...
          }:
          let

            workspace = inputs.uv2nix.lib.workspace.loadWorkspace {
              workspaceRoot = ./.;
              # workspaceRoot = lib.fileset.toSource {
              #   root = ./.;
              #   fileset = lib.fileset.difference ./. ./flake.nix;
              # };
            };

            pyprojectOverrides =
              # See https://pyproject-nix.github.io/uv2nix/patterns/overriding-build-systems.html
              final: prev:
              builtins.mapAttrs
                (
                  name: spec:
                  prev.${name}.overrideAttrs (old: {
                    nativeBuildInputs = old.nativeBuildInputs ++ final.resolveBuildSystem spec;
                  })
                )
                {
                  pyflyby = {
                    meson-python = [ ];
                    pybind11 = [ ];
                  };
                };
            python = pkgs.python313;
            hacks = pkgs.callPackage inputs.pyproject-nix.build.hacks { };
            pythonSet =
              (pkgs.callPackage inputs.pyproject-nix.build.packages {
                inherit python;
              }).overrideScope
                (
                  lib.composeManyExtensions [
                    inputs.pyproject-build-systems.overlays.wheel
                    (workspace.mkPyprojectOverlay {
                      sourcePreference = "wheel";
                      dependencies = workspace.deps.default;
                    })
                    (inputs.uv2nix_hammer_overrides.overrides pkgs)
                    pyprojectOverrides
                    (final: prev: {
                      pyflyby = prev.pyflyby.overrideAttrs (old: {
                        propagatedBuildInputs = old.buildInputs or [ ] ++ [
                          pkgs.ninja
                        ];
                      });
                      # Ignore RDMA dependencies for nvidia-cufile - they are optional
                      # and only needed for InfiniBand/GPUDirect RDMA environments
                      nvidia-cufile-cu12 = prev.nvidia-cufile-cu12.overrideAttrs (old: {
                        autoPatchelfIgnoreMissingDeps = [
                          "libmlx5.so.1"
                          "librdmacm.so.1"
                          "libibverbs.so.1"
                        ];
                      });
                      # Ignore HPC cluster dependencies for nvidia-nvshmem - they are optional
                      # and only needed for multi-node distributed training environments
                      nvidia-nvshmem-cu12 = prev.nvidia-nvshmem-cu12.overrideAttrs (old: {
                        autoPatchelfIgnoreMissingDeps = [
                          "libmlx5.so.1" # InfiniBand
                          "libmpi.so.40" # MPI
                          "libucs.so.0" # UCX
                          "libucp.so.0" # UCX
                          "libpmix.so.2" # PMIx
                          "liboshmem.so.40" # OpenSHMEM
                          "libfabric.so.1" # libfabric
                        ];
                      });
                      # Use nixpkgs torch-bin which has proper CUDA integration
                      # This replaces PyPI torch with the well-tested nixpkgs version
                      # that correctly handles all CUDA dependencies via cudaPackages
                      torch = hacks.nixpkgsPrebuilt {
                        from = python.pkgs.torch-bin;
                      };
                      bitsandbytes = hacks.nixpkgsPrebuilt {
                        from = python.pkgs.bitsandbytes;
                      };
                      ray = hacks.nixpkgsPrebuilt {
                        from = python.pkgs.ray;
                      };
                      # NIXL for Ray Direct Transport zero-copy GPU tensor transfer
                      # Ignore optional plugins and driver libs, add required libs
                      nixl-cu12 = prev.nixl-cu12.overrideAttrs (old: {
                        autoPatchelfIgnoreMissingDeps = [
                          # Driver libs - loaded from /run/opengl-driver/lib at runtime
                          "libcuda.so.1"
                          "libnvidia-ml.so.1"
                          # UCX optional transports - RDMA/InfiniBand (not needed for single-node)
                          "librdmacm.so.1"
                          "libefa.so.1" # AWS EFA
                          "libgdrapi.so.2" # GPUDirect RDMA (gdrcopy)
                          "libibmad.so.5" # InfiniBand management
                          "libibumad.so.3" # InfiniBand userspace MAD
                          # NIXL optional plugins - RDMA/InfiniBand
                          "libfabric.so.1"
                          # NIXL optional plugins - GPUDirect Storage
                          "libcufile.so.0"
                          # NIXL optional plugins - S3/object storage
                          "libaws-cpp-sdk-s3.so"
                          "libaws-cpp-sdk-core.so"
                          "libaws-crt-cpp.so"
                          # Optional - hardware locality (performance optimization)
                          "libhwloc.so.15"
                        ];
                        buildInputs = (old.buildInputs or [ ]) ++ [
                          # Required CUDA runtime libs
                          pkgs.cudaPackages.cuda_cudart
                          # OpenSSL 3.x for gRPC, etcd, AWS SDK, curl
                          pkgs.openssl
                        ];
                      });
                    })
                  ]
                );
            members = [
              "ol"
            ]
            ++ lib.optionals (builtins.pathExists ./lib) (
              lib.pipe ./lib [
                builtins.readDir
                builtins.attrNames
                (builtins.filter (name: builtins.pathExists ./lib/${name}/pyproject.toml))
              ]
            );
            editableOverlay = workspace.mkEditablePyprojectOverlay {
              root = "$REPO_ROOT";
              inherit members;
            };
            editablePythonSet = pythonSet.overrideScope (
              lib.composeManyExtensions [
                editableOverlay
                pyprojectOverrides
                (
                  final: prev:
                  lib.attrsets.genAttrs members (
                    name:
                    prev.${name}.overrideAttrs (old: {
                      # It's a good idea to filter the sources going into an editable build
                      # so the editable package doesn't have to be rebuilt on every change.
                      src = lib.fileset.toSource rec {
                        root = (lib.sources.cleanSourceWith { src = old.src; }).origSrc;
                        fileset = lib.fileset.unions (
                          [
                            /${root}/pyproject.toml
                            (lib.fileset.maybeMissing /${root}/README.md)
                            (lib.fileset.maybeMissing /${root}/LICENSE)
                          ]
                          ++ (
                            let
                              # Helper to get files in a dir matching a predicate
                              getFiles =
                                dir: pred:
                                if builtins.pathExists dir then
                                  let
                                    entries = builtins.readDir dir;
                                  in
                                  map (n: dir + "/${n}") (
                                    builtins.filter (n: entries.${n} == "regular" && pred n) (builtins.attrNames entries)
                                  )
                                else
                                  [ ];

                              # Helper to get __init__.py in subdirs
                              getSubInit =
                                dir:
                                if builtins.pathExists dir then
                                  let
                                    entries = builtins.readDir dir;
                                    subdirs = builtins.filter (n: entries.${n} == "directory") (builtins.attrNames entries);
                                  in
                                  map (n: dir + "/${n}/__init__.py") (
                                    builtins.filter (n: builtins.pathExists (dir + "/${n}/__init__.py")) subdirs
                                  )
                                else
                                  [ ];

                              rootPy = getFiles root (n: lib.hasSuffix ".py" n);
                              rootSubInit = getSubInit root;

                              srcPath = root + "/src";
                              srcPy = getFiles srcPath (n: lib.hasSuffix ".py" n);
                              srcSubInit = getSubInit srcPath;
                            in
                            rootPy ++ rootSubInit ++ srcPy ++ srcSubInit
                          )
                        );
                      };
                    })
                  )
                )
              ]
            );
            ol-dev-env =
              (editablePythonSet.mkVirtualEnv "ol-dev-env" workspace.deps.all).overrideAttrs
                (old: {
                  venvIgnoreCollisions = [ "*" ];
                });
            yamlFormat = pkgs.formats.yaml { };
            # Modern CUDA setup using individual packages instead of legacy cudatoolkit
            cudaEnv = pkgs.symlinkJoin {
              name = "cuda-env";
              paths = with pkgs.cudaPackages; [
                cuda_nvcc
                cuda_cudart
                cuda_cccl
                libcublas
                libcusparse
                libcufft
                libnvjitlink
              ];
            };

            start-jupyter-lab = pkgs.writeShellApplication {
              name = "start-jupyter-lab";
              runtimeInputs = [
                ol-dev-env
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
            imports = [
              "${inputs.nixpkgs}/nixos/modules/misc/nixpkgs.nix"
            ];
            nixpkgs.hostPlatform = system;
            nixpkgs.config.allowUnfree = true;
            packages.default =
              (pythonSet.mkVirtualEnv "ol-env" workspace.deps.default).overrideAttrs
                (old: {
                  venvIgnoreCollisions = [ "*" ];
                });
            packages.ol-dev-env = ol-dev-env;

            devShells.default = pkgs.mkShell {
              env = {
                # Force uv to use Python interpreter from venv
                UV_PYTHON = "${ol-dev-env}/bin/python";

                # Prevent uv from downloading managed Python's
                UV_PYTHON_DOWNLOADS = "never";

                # Don't create venv using uv
                UV_NO_SYNC = "1";

                NIX_LD = "";
                NIX_LD_LIBRARY_PATH = "";
                LD_AUDIT = "${pkgs.ld-audit-search-mod}/lib/libld-audit-search-mod.so";
                GLIBC_TUNABLES = "glibc.rtld.optional_static_tls=2000";
                LD_AUDIT_SEARCH_MOD_CONFIG = toString (
                  yamlFormat.generate "lasm-config.yaml" {
                    rules = [
                      {
                        cond.rtld = "any";
                        default.prepend = [
                          { dir = "${pkgs.stdenv.cc.cc.lib}/lib"; }
                        ];
                      }
                      {
                        cond.rtld = "any";
                        libpath.save = true;
                        default.prepend = [
                          { saved = "libpath"; }
                        ];
                      }
                    ];
                  }
                );
              };
              packages = [
                ol-dev-env
                pkgs.nixfmt
                pkgs.shellcheck
                pkgs.uv
                start-jupyter-lab
              ];

              shellHook = ''
                # Undo dependency propagation by nixpkgs.
                unset PYTHONPATH

                # Get repository root using git. This is expanded at runtime by the editable `.pth` machinery.
                export REPO_ROOT=$(git rev-parse --show-toplevel)

                # Create symlink .venv -> ol-dev-env
                rm -rf .venv
                ln -sf ${ol-dev-env} .venv

                # Compute hash from current path for Jupyter URL
                PWD_HASH=$(echo -n "$PWD" | sha256sum | cut -c1-8)
                # Parse hex and map to port range 11000-11999 using bash native arithmetic
                JUPYTER_PORT=$((16#$PWD_HASH % 1000 + 11000))
                JUPYTER_URL="http://localhost:$JUPYTER_PORT"
                export JUPYTER_PORT
                export JUPYTER_URL

                # Check if JUPYTER_TOKEN is set, if not generate one
                if [ -z "''${JUPYTER_TOKEN:-}" ]; then
                  echo "JUPYTER_TOKEN not found, generating a new one..." >&2
                  JUPYTER_TOKEN=$(${lib.escapeShellArg (lib.getExe pkgs.xxd)} -c 32 -l 32 -p /dev/urandom)
                  export JUPYTER_TOKEN

                  # Create .env if it doesn't exist
                  touch .env

                  # Add JUPYTER_TOKEN to .env
                  echo "JUPYTER_TOKEN=$JUPYTER_TOKEN" >> .env
                  echo "Generated and saved JUPYTER_TOKEN to .env"
                fi


                # VSCode's Codex extension cannot access project specific environment variables other than PATH, thus we create a wrapper script that executes commands via direnv in the current working directory.
                #
                # This wrapper can then be used in codex config.toml like so:
                #
                # ```
                # [mcp_servers.jupyter]
                # command = "vscode-codex-direnv-exec-pwd"
                # args = ["jupyter-mcp-server"]
                # ```

                printf "#!%s\nexec %q exec %q %s" \
                ${lib.escapeShellArg (lib.getExe pkgs.bash)} \
                ${lib.escapeShellArg (lib.getExe pkgs.direnv)} \
                "$PWD" \
                '"$@"' \
                > .direnv/bin/vscode-codex-direnv-exec-pwd
                chmod +x .direnv/bin/vscode-codex-direnv-exec-pwd
              '';
            };

          };
      }
    );
}
