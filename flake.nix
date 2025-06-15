{
  nixConfig = {
    # Required to import YAML files
    allow-import-from-derivation = true;
    extra-substituters = [
      "https://cache.nixos.org"
      "https://devenv.cachix.org"
      "https://nix-community.cachix.org"
    ];
  };
  inputs = {
    flake-parts.url = "github:hercules-ci/flake-parts/main";
    systems.url = "github:nix-systems/default";
    devenv-root = {
      url = "file+file:///dev/null";
      flake = false;
    };
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    yaml.url = "github:jim3692/yaml.nix";
    yaml.inputs.nixpkgs.follows = "nixpkgs";
  };
  outputs = inputs: inputs.flake-parts.lib.mkFlake { inherit inputs; } {
    imports = [
      ./modules/lib.nix
    ];
  };
}

