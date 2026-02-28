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
              mixinv2-workspace = prev.mixinv2-workspace.overrideAttrs (_: {
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
            "mixinv2"
            "mixinv2-library"
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

          mixinv2-dev-env =
            (editablePythonSet.mkVirtualEnv "mixinv2-dev-env" workspace.deps.all).overrideAttrs
              (old: {
                venvIgnoreCollisions = [ "*" ];
              });

          # --- Supplementary material for double-blind review ---

          sphinxEnv =
            (pythonSet.mkVirtualEnv "sphinx-env"
              (builtins.removeAttrs workspace.deps.all [ "mixinv2-workspace" ])
            ).overrideAttrs (old: {
              venvIgnoreCollisions = [ "*" ];
            });

          supplementarySourceFiles = lib.fileset.toSource {
            root = ../.;
            fileset = lib.fileset.unions [
              ../mixinv2/src
              ../mixinv2/pyproject.toml
              ../mixinv2/README.md
              ../mixinv2/docs
              ../mixinv2-library/src
              ../mixinv2-library/pyproject.toml
              ../mixinv2.schema.json
              ../tests
              ../pyproject.toml
              ../LICENSE
              ../README.md
            ];
          };

          reviewerReadme = pkgs.writeText "README.md" ''
            # MIXINv2 — Supplementary Material

            This archive contains the source code and tests for MIXINv2, the reference
            implementation of inheritance-calculus.

            ## Directory Structure

            - `docs` — Built HTML documentation
            - `mixinv2/src/mixinv2/` — Python implementation of the MIXINv2 runtime
            - `mixinv2-library/src/mixinv2_library/Builtin/` — Standard library (`.oyaml` files):
              Boolean logic, Nat arithmetic, BinNat arithmetic, visitors, equality
            - `tests/` — Test suite (see below)

            ## Paper Examples in the Test Suite

            The case study examples from the paper are implemented as `.oyaml` files
            and exercised by `pytest` tests:

            | Paper section | `.oyaml` file(s) | Test file |
            |---|---|---|
            | Case Study: Nat arithmetic | `mixinv2-library/.../NatData.oyaml`, `NatPlus.oyaml`, `NatEquality.oyaml`, `NatVisitor.oyaml`, `NatDecrement.oyaml`, `tests/NatConstants.oyaml`, `tests/ArithmeticTest.oyaml` | `tests/test_nat_arithmetic.py` |
            | Case Study: BinNat arithmetic | `mixinv2-library/.../BinNat*.oyaml`, `tests/BinNatArithmeticTest.oyaml` | `tests/test_bin_nat_arithmetic.py` |
            | Case Study: Cartesian product (relational semantics) | `tests/CartesianProductTest.oyaml` | `tests/test_cartesian_product.py` |
            | Boolean logic | `mixinv2-library/.../Boolean*.oyaml`, `tests/ChurchBooleanTest.oyaml` | `tests/test_church_boolean.py` |
            | Fibonacci | `tests/FibonacciTest.oyaml`, `tests/FibonacciLibrary.oyaml` | `tests/test_fibonacci.py` |
            | Function color blindness | `tests/fixtures/app_oyaml/` | `tests/test_stdlib_python_port.py` |
            | Expression Problem | Composition of separate `.oyaml` files without modification | `tests/test_nat_arithmetic.py`, `tests/test_bin_nat_arithmetic.py` |

            ## Running Tests

            ```
            pip install -e ".[docs]" -e mixinv2-library
            pytest tests/
            ```
          '';

          anonymizedSource = pkgs.runCommand "anonymized-source" {
            nativeBuildInputs = [ pkgs.file ];
          } ''
            cp -r ${supplementarySourceFiles} $out
            chmod -R u+w $out

            # Replace README with reviewer-oriented version
            cp ${reviewerReadme} $out/README.md

            # Anonymize all text files
            find $out -type f | while read f; do
              if file --mime-type "$f" | grep -qE 'text/|application/json'; then
                sed -i \
                  -e 's|yang-bo@yang-bo.com|anonymous@example.com|g' \
                  -e "s|Yang, Bo|Anonymous, Author|g" \
                  -e 's|Bo Yang|Anonymous Author|g' \
                  -e 's|Figure AI Inc\.|Anonymous Institution|g' \
                  -e 's|Figure AI|Anonymous Institution|g' \
                  -e 's|github\.com/Atry/MIXINv2|github.com/anonymous-author/anonymous-repo|g' \
                  -e 's|github\.com/Atry/overlay|github.com/anonymous-author/anonymous-repo|g' \
                  -e 's|github\.com/Atry/MIXIN|github.com/anonymous-author/anonymous-repo|g' \
                  -e "s|'Atry'|'anonymous-author'|g" \
                  -e 's|"Atry"|"anonymous-author"|g' \
                  "$f"
              fi
            done
          '';

          htmlDocs = pkgs.runCommand "mixinv2-html-docs" {
            nativeBuildInputs = [ sphinxEnv ];
          } ''
            # Mutable copy for sphinx-apidoc output + conf.py patching
            cp -r ${anonymizedSource}/mixinv2/docs docs-build
            chmod -R u+w docs-build

            # Patch out git rev-parse call (no git repo in sandbox)
            # The original is a multiline expression:
            #   _git_commit = subprocess.check_output(
            #       ["git", "rev-parse", "HEAD"], text=True
            #   ).strip()
            sed -i '/^_git_commit = subprocess/,/\.strip()$/c\_git_commit = "anonymous"' docs-build/conf.py

            # Generate API docs
            sphinx-apidoc --implicit-namespaces -o docs-build/api ${anonymizedSource}/mixinv2/src/mixinv2

            # Build HTML
            sphinx-build -b html docs-build $out
          '';

          supplementaryMaterial = pkgs.stdenv.mkDerivation {
            name = "supplementary-material.zip";
            nativeBuildInputs = [ pkgs.zip pkgs.unzip ];
            dontUnpack = true;

            buildPhase = ''
              mkdir -p staging/mixinject-supplementary

              # Copy anonymized source (includes mixinv2/docs/ source)
              cp -r ${anonymizedSource}/* staging/mixinject-supplementary/
              chmod -R u+w staging/mixinject-supplementary

              # Add built HTML docs under mixinv2/docs/_build/html/
              mkdir -p staging/mixinject-supplementary/mixinv2/docs/_build
              cp -r ${htmlDocs} staging/mixinject-supplementary/mixinv2/docs/_build/html

              # Copy HTML docs to top-level docs/ directory
              cp -r staging/mixinject-supplementary/mixinv2/docs/_build/html staging/mixinject-supplementary/docs

              cd staging
              zip -r --latest-time $TMPDIR/supplementary-material.zip mixinject-supplementary
            '';

            installPhase = ''
              cp $TMPDIR/supplementary-material.zip $out
            '';

            doInstallCheck = true;
            installCheckPhase = ''
              unzip $out -d $TMPDIR/verify

              # No identity leaks
              if grep -rli "Bo Yang" $TMPDIR/verify/mixinject-supplementary/; then
                echo "FAIL: Found 'Bo Yang'" >&2; exit 1
              fi
              if grep -rli "yang-bo" $TMPDIR/verify/mixinject-supplementary/; then
                echo "FAIL: Found 'yang-bo'" >&2; exit 1
              fi
              if grep -rli "Figure AI" $TMPDIR/verify/mixinject-supplementary/; then
                echo "FAIL: Found 'Figure AI'" >&2; exit 1
              fi
              if grep -rl "Atry" $TMPDIR/verify/mixinject-supplementary/; then
                echo "FAIL: Found 'Atry'" >&2; exit 1
              fi

              # HTML docs present
              test -d $TMPDIR/verify/mixinject-supplementary/docs
              test -f $TMPDIR/verify/mixinject-supplementary/docs/index.html
              test -f $TMPDIR/verify/mixinject-supplementary/mixinv2/docs/_build/html/index.html

              # Excluded items absent
              if find $TMPDIR/verify/mixinject-supplementary -path '*inheritance-calculus*' \
                -o -path '*overlay-language*' | grep -q .; then
                echo "FAIL: Found excluded directory" >&2; exit 1
              fi

              # Anonymization applied
              grep -rl "Anonymous Author" $TMPDIR/verify/mixinject-supplementary/ > /dev/null
            '';
          };
        in
        {
          packages.default =
            (pythonSet.mkVirtualEnv "mixinv2-env" (builtins.removeAttrs workspace.deps.default [ "mixinv2-workspace" ])).overrideAttrs
              (old: {
                venvIgnoreCollisions = [ "*" ];
              });
          packages.mixinv2-dev-env = mixinv2-dev-env;
          packages.supplementary-material = supplementaryMaterial;

          ml-ops.devcontainer.devenvShellModule = {
            packages = [
              mixinv2-dev-env
              pkgs.uv
            ];
            env = {
              UV_PYTHON = "${mixinv2-dev-env}/bin/python";
              UV_PYTHON_DOWNLOADS = "never";
              UV_NO_SYNC = "1";
            };
            enterShell = ''
              unset PYTHONPATH
              export REPO_ROOT=$(git rev-parse --show-toplevel)
              rm -rf .venv
              ln -sf ${mixinv2-dev-env} .venv
            '';
          };
        };
    };
}
