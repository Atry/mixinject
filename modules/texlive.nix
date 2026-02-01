{ ... }:
{
  imports = [
    ./dev.nix
  ];
  partitions.dev.module.perSystem = { pkgs, ... }: {
    ml-ops.devcontainer.devenvShellModule = {
      packages = [
        pkgs.tex-fmt
      ];
      languages = {
        texlive = {
          enable = true;
          packages = [
            "scheme-medium"
            "cjk"
            "xpinyin"
            "latexmk"
            # acmart dependencies not in scheme-medium
            "xstring"
            "totpages"
            "environ"
            "trimspaces"
            "ncctools"
            "comment"
            "pbalance"
            "libertine"
            "inconsolata"
            "newtx"
            "hyperxmp"
            "ifmtarg"
            "draftwatermark"
            "preprint"
            "tex-gyre"
          ];
        };
      };
    };
  };
}
