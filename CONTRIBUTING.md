# Contributing

## Prerequisites

- [Nix](https://nixos.org/) with flakes enabled
- [direnv](https://direnv.net/) (recommended)

## Development Environment

This project uses Nix flakes to manage dependencies. After modifying any `.nix` file (e.g., `modules/texlive.nix`), the current shell environment becomes stale. You must use `direnv exec .` to run commands with the updated environment:

```sh
direnv exec . latexmk -pdf -interaction=nonstopmode mixin-calculus/mixin-calculus.tex
```

Alternatively, restart your shell or run `direnv reload` to pick up the changes.

## Building the Paper

```sh
cd mixin-calculus
latexmk -pdf -interaction=nonstopmode mixin-calculus.tex
```

## Adding Test Files

When adding new test files (e.g., `tests/src/my_test.mixin.yaml`), you **must** use `git add` before Nix can see them:

```sh
git add tests/src/my_test.mixin.yaml
direnv exec . nix run .#update-tests-snapshot
```

Nix uses Git to track files in the repository. Untracked files are invisible to Nix commands.

## Adding TeXLive Packages

TeXLive packages are declared in `modules/texlive.nix`. Note that package names in nixpkgs may differ from CTAN names (e.g., `zi4` is `inconsolata`, `newtxmath` is `newtx`).

## Naming Conventions

- **Do not use single-letter variable names.** Use descriptive names that convey the purpose of the variable.
- **Do not use abbreviated or truncated English words** (e.g., `expr` for `expression`, `env` for `environment`, `val` for `value`). Write out the full word. The fact that an abbreviation is widely used in the industry does not justify its use here.
- **Exception:** established notations that are part of a fixed formal system are permitted, but these are limited to very few cases (e.g., `T` for a type variable in a typing judgment, `Γ` for a typing context). When in doubt, spell it out.
