{ ... }: {
  imports = [ ./dev.nix ];
  partitions.dev.module.perSystem = { pkgs, lib, ... }: {
    ml-ops.devcontainer.devenvShellModule = {
      packages = [ pkgs.tex-fmt ];
      scripts.package-arxiv.exec = ''
        cd inheritance-calculus
        ${lib.getExe pkgs.gnutar} -czvf arxiv-submission.tar.gz \
          -C . \
          *.tex \
          *.bib \
          *.bst \
          *.cls
      '';
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
