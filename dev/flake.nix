{
  inputs = {
    nix-ml-ops.url = "github:Atry/nix-ml-ops";
    nix-ml-ops.inputs.systems.url = "github:nix-systems/default";
    # Required by devenv's `containers` feature, which looks up `inputs.nix2container` at the top level
    nix2container.follows = "nix-ml-ops/nix2container";
  };
  outputs = inputs: { };
}
