{ inputs, ... }:
{
  imports = [
    ./dev.nix
  ];
  partitions.dev.module.perSystem =
    { pkgs
    , lib
    , ...
    }:
    let
      doi-mcp-src = inputs.doi-mcp;

      # Pack doi-mcp as a tarball so npm extracts it instead of symlinking,
      # which allows proper dependency resolution.
      # Also remove the bin field to avoid chmod on read-only store paths.
      doi-mcp-tarball = pkgs.runCommand "doi-mcp-1.0.0.tgz" {
        nativeBuildInputs = [ pkgs.jq ];
      } ''
        mkdir -p work/package
        cp -r ${doi-mcp-src}/* work/package/
        chmod -R u+w work
        jq 'del(.bin)' work/package/package.json > work/package/package.json.tmp
        mv work/package/package.json.tmp work/package/package.json
        cd work
        tar czf $out package
      '';

      packageJSON = lib.importJSON ../package.json;
      packageLockJSON = lib.importJSON ../package-lock.json;

      # Remove the bin field from the lockfile entry
      patchedPackageLock = packageLockJSON // {
        packages = packageLockJSON.packages // {
          "node_modules/doi-mcp" = builtins.removeAttrs
            packageLockJSON.packages."node_modules/doi-mcp"
            [ "bin" ];
        };
      };

      npmDeps = pkgs.importNpmLock {
        package = packageJSON;
        packageLock = patchedPackageLock;
        packageSourceOverrides = {
          "node_modules/doi-mcp" = doi-mcp-tarball;
        };
      };

      node-modules = pkgs.stdenv.mkDerivation {
        pname = "doi-mcp-node-modules";
        version = "1.0.0";

        dontUnpack = true;

        inherit npmDeps;

        npmFlags = [ "--include=dev" ];

        nativeBuildInputs = [
          pkgs.nodejs
          pkgs.nodejs.passthru.python
          pkgs.importNpmLock.npmConfigHook
        ];

        passAsFile = [
          "package"
          "packageLock"
        ];

        package = builtins.toJSON packageJSON;
        packageLock = builtins.toJSON patchedPackageLock;

        postPatch = ''
          cp --no-preserve=mode "$packagePath" package.json
          cp --no-preserve=mode "$packageLockPath" package-lock.json
        '';

        installPhase = ''
          runHook preInstall
          mkdir $out
          [[ -d node_modules ]] && mv node_modules $out/
          runHook postInstall
        '';
      };

      doi-mcp = pkgs.stdenv.mkDerivation {
        pname = "doi-mcp";
        version = "1.0.0";

        dontUnpack = true;

        nativeBuildInputs = [ pkgs.makeWrapper ];

        installPhase = ''
          runHook preInstall

          mkdir -p $out/lib/node_modules/doi-mcp
          cp ${doi-mcp-src}/package.json $out/lib/node_modules/doi-mcp/
          cp -r ${doi-mcp-src}/dist $out/lib/node_modules/doi-mcp/

          cp -r --no-preserve=mode ${node-modules}/node_modules $out/lib/node_modules/doi-mcp/node_modules
          rm -rf $out/lib/node_modules/doi-mcp/node_modules/doi-mcp

          mkdir -p $out/bin
          makeWrapper ${lib.getExe pkgs.nodejs} $out/bin/doi-mcp \
            --add-flags "$out/lib/node_modules/doi-mcp/dist/index.js"

          runHook postInstall
        '';

        meta = {
          description = "MCP server for verifying academic citations against multiple databases";
          license = lib.licenses.mit;
          mainProgram = "doi-mcp";
        };
      };
    in
    {
      packages.doi-mcp = doi-mcp;

      ml-ops.devcontainer.devenvShellModule.packages = [
        doi-mcp
      ];
    };
}
