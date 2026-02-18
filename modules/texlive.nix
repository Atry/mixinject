{ ... }: {
  imports = [ ./dev.nix ];
  partitions.dev.module.perSystem = { pkgs, ... }:
    let
      package-arxiv = pkgs.writeShellApplication {
        name = "package-arxiv";
        runtimeInputs = [ pkgs.gnutar ];
        text = ''
          tar -czvf arxiv-submission.tar.gz \
            -C mixin-calculus \
            *.tex \
            *.bib \
            *.bst \
            *.cls
        '';
      };
    in {
      ml-ops.devcontainer.devenvShellModule = {
        packages = [ pkgs.tex-fmt package-arxiv ];
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
