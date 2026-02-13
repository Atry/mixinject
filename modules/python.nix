{ ... }:
{
  imports = [
    ./dev.nix
  ];
  partitions.dev.module =
    { inputs
    , ...
    }: {
      perSystem =
        { pkgs
        , lib
        , ...
        }:
        let
          workspace = inputs.uv2nix.lib.workspace.loadWorkspace {
            workspaceRoot = ../.;
          };

          pyprojectOverrides =
            final: prev:
            (builtins.mapAttrs
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
                uv-dynamic-versioning = {
                  hatchling = [ ];
                };
              }
            )
            // {
              overlay = prev.overlay.overrideAttrs (_: {
                buildPhase = "mkdir -p $out";
                installPhase = "true";
                nativeBuildInputs = [ ];
              });
            };

          python = pkgs.python313;

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
                  })
                ]
              );

          members = [
            "overlay-language"
            "overlay-library"
          ];

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

                            getInitPy =
                              dir: depth:
                              if depth <= 0 || !builtins.pathExists dir then
                                [ ]
                              else
                                let
                                  entries = builtins.readDir dir;
                                  subdirs = builtins.filter (n: entries.${n} == "directory") (builtins.attrNames entries);
                                  initFiles = if builtins.pathExists (dir + "/__init__.py") then [ (dir + "/__init__.py") ] else [ ];
                                in
                                initFiles ++ lib.concatMap (n: getInitPy (dir + "/${n}") (depth - 1)) subdirs;

                            rootPy = getFiles root (n: lib.hasSuffix ".py" n);

                            srcPath = root + "/src";
                            srcPy = getFiles srcPath (n: lib.hasSuffix ".py" n);
                            srcInitPy = getInitPy srcPath 3;
                          in
                          rootPy ++ srcPy ++ srcInitPy
                        )
                      );
                    };
                  })
                )
              )
            ]
          );

          overlay-dev-env =
            (editablePythonSet.mkVirtualEnv "overlay-dev-env" workspace.deps.all).overrideAttrs
              (old: {
                venvIgnoreCollisions = [ "*" ];
              });
        in
        {
          packages.default =
            (pythonSet.mkVirtualEnv "overlay-env" (builtins.removeAttrs workspace.deps.default [ "overlay" ])).overrideAttrs
              (old: {
                venvIgnoreCollisions = [ "*" ];
              });
          packages.overlay-dev-env = overlay-dev-env;

          ml-ops.devcontainer.devenvShellModule = {
            packages = [
              overlay-dev-env
              pkgs.uv
            ];
            env = {
              UV_PYTHON = "${overlay-dev-env}/bin/python";
              UV_PYTHON_DOWNLOADS = "never";
              UV_NO_SYNC = "1";
            };
            enterShell = ''
              unset PYTHONPATH
              export REPO_ROOT=$(git rev-parse --show-toplevel)
              rm -rf .venv
              ln -sf ${overlay-dev-env} .venv
            '';
          };
        };
    };
}
