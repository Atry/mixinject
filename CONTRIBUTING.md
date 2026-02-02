# Contributing

## About This Repository

This repository contains MIXIN, an executable implementation of MixinCalculus using YAML syntax. The accompanying paper (`mixin-calculus/mixin-calculus.tex`) presents the theoretical foundations of MixinCalculus and targets the Onward! conference.

### Supplementary Material

This repository serves as one of two supplementary materials for the paper:

1. **This repository (MIXIN implementation)**: The core evaluator and test suite validate every construction described in the paper, including Church-encoded booleans and natural numbers, CPS-agnostic programs with escape and multi-exit continuations, the Expression Problem solution via free composition, and immutable trie operations with dynamic lookup and deletion.

2. **ratarmount PR**: A proof-of-concept implementation of mixin-based union file system composition, demonstrating that MixinCalculus patterns (late binding, dynamic dispatch, lexical scoping) emerge naturally in union mount systems. This is an open pull request at https://github.com/mxmlnkn/ratarmount/pull/163 and is not part of ratarmount's released versions.

Both supplementary materials are authored by the paper's author. Citations to them in the paper use the `\selfcite` command, which hides the citation (and its identifying URL) under anonymous review and shows it in non-anonymous mode (e.g., arXiv preprint). The corresponding bib entries are `mixin2025` (this repository) and `ratarmount2025` (the ratarmount PR).

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

### Debugging Test Failures

If you encounter errors when updating tests, use `--show-trace` to see the full stack trace:

```sh
nix run .#update-tests-snapshot --show-trace
```

Common issues:
- **Stack overflow**: Check for infinite recursion in self-references
- **YAML parsing errors**: Avoid using `====` or similar decorative comment lines (they may be misinterpreted as file paths)
- **Missing properties**: Ensure all referenced fields exist in composed mixins

To test a single file without updating the full snapshot:

```sh
nix eval --impure --show-trace --expr '
let
  lib = (builtins.getFlake "git+file://'$(pwd)'").lib;
  yaml = (builtins.getFlake "git+file://'$(pwd)'").inputs.yaml.lib.fromYaml;
  ast = yaml (builtins.readFile ./tests/src/my_test.mixin.yaml);
in
  builtins.attrNames ast
'
```

## Adding TeXLive Packages

TeXLive packages are declared in `modules/texlive.nix`. Note that package names in nixpkgs may differ from CTAN names (e.g., `zi4` is `inconsolata`, `newtxmath` is `newtx`).

## Naming Conventions

- **Do not use single-letter variable names.** Use descriptive names that convey the purpose of the variable.
- **Do not use abbreviated or truncated English words** (e.g., `expr` for `expression`, `env` for `environment`, `val` for `value`). Write out the full word. The fact that an abbreviation is widely used in the industry does not justify its use here.
- **Exception:** established notations that are part of a fixed formal system are permitted, but these are limited to very few cases (e.g., `T` for a type variable in a typing judgment, `Γ` for a typing context). When in doubt, spell it out.

### MIXIN File Naming Conventions

In `.mixin.yaml` files, the following naming conventions apply:

| Concept | Case | Examples |
|---------|------|----------|
| Module / namespace | `snake_case` | `boolean`, `nat`, `arithmetic`, `algorithms` |
| Type / class / trait | `PascalCase` | `Boolean`, `Nat`, `BinNat`, `Semigroup` |
| Constructor / value | `PascalCase` | `True`, `False`, `Zero`, `Succ`, `ListNil` |
| Operation / function | `PascalCase` | `BooleanAnd`, `NatAdd`, `PolyEquality` |
| Implementation binding | `PascalCase` | `NatAddSemigroup`, `BooleanOrSemigroup` |
| Data field / parameter | `snake_case` | `element_type`, `left`, `right`, `on_true` |
| Temporary variable | `_snake_case` | `_applied_addend`, `_applied_augend`, `_applied_left` |

**Qualified `this`** is a reference of the form `[MixinName, [property, path]]` where `MixinName` is the name of an enclosing mixin resolved via `selfName`. It resolves through dynamic `self`, meaning the path is navigated on the fully composed evaluation — not just the mixin's own definition. The mixin name in a qualified `this` must be `PascalCase` to avoid name shadowing:

```yaml
# [NatAdd, [addend]] is a qualified this — NatAdd refers to the mixin being defined
# [NatAdd, [successor]] is also qualified this — successor is inherited from Nat
NatAdd:
  - [types, Nat]
  - augend:
      - [types, Nat]
    addend:
      - [types, Nat]
    _applied_addend:                   # Temporary variable (not qualified this)
      - [NatAdd, [addend]]            # ← Qualified this: NatAdd.self.addend
      - successor:
          - [NatAdd, [successor]]     # ← Qualified this: NatAdd.self.successor
    result:
      - [_applied_addend, result]     # ← Just a variable reference, not qualified this

# WRONG: lowercase mixin name — prone to shadowing
nat_add:
  - [types, Nat]
  - result:
      - [nat_add, [addend]]   # "nat_add" can be shadowed by a property named "nat_add"
```

The risk: if any ancestor in the scope chain has a property matching the lowercase name (e.g., `result`, `argument`, `nat_add`), the reference resolves to the wrong binding. PascalCase names like `NatAdd` are distinctive enough to avoid accidental collisions with `snake_case` data fields.

**When to use qualified this vs. direct references**:
- Use `[property]` or `[property, subproperty]` when the first segment is accessible in the current lexical scope.
- Use `[MixinName, [property, path]]` when the property is only accessible through the dynamic `self` of an enclosing mixin (e.g., inherited properties that are shadowed in the current scope).
- For module-level references within the same module, prefer dropping the module prefix: `[types, Nat]` instead of `[stdlib, [types, Nat]]`.

## MIXIN Design Patterns

The following patterns are established by the stdlib (`stdlib/stdlib.mixin.yaml`) and test suite.

### Pattern 1: Church Encoding via Observer Interfaces

Types are defined as observer interfaces with holes (`{}`). Values are constructors that select which observer branch to return.

```yaml
# Type definition: the observer interface
Boolean:
  on_true: {}
  on_false: {}
  result: {}

# Constructor: selects on_true branch
"True":
  - [types, Boolean]
  - result:
      - ["True", [on_true]]     # Qualified this — resolves to caller's on_true

# Constructor: selects on_false branch
"False":
  - [types, Boolean]
  - result:
      - ["False", [on_false]]
```

The key insight: `["True", [on_true]]` uses qualified this to access `on_true` through `True`'s dynamic `self`. When `True` is composed with observer arguments, `on_true` resolves to the composed evaluation's `on_true`, not `True`'s own definition.

### Pattern 2: Church Encoding Fold (Non-Recursive Arithmetic)

Church numerals encode iteration in their structure. Arithmetic operations delegate recursion to the numeral itself rather than using explicit self-references. This avoids infinite evaluation trees.

```yaml
# add(augend, addend)(successor, zero) = augend(successor, addend(successor, zero))
NatAdd:
  - [types, Nat]                       # Inherits successor/zero observer interface
  - augend:
      - [types, Nat]
    addend:
      - [types, Nat]
    _applied_addend:                   # Temporary: fold addend with the caller's successor/zero
      - [NatAdd, [addend]]            # Qualified this
      - successor:
          - [NatAdd, [successor]]     # Qualified this
        zero:
          - [NatAdd, [zero]]          # Qualified this
    _applied_augend:                   # Temporary: fold augend, chaining after addend
      - [NatAdd, [augend]]            # Qualified this
      - successor:
          - [NatAdd, [successor]]     # Qualified this
        zero:
          - [_applied_addend, result]  # Variable reference (not qualified this)
    result:
      - [_applied_augend, result]
```

This pattern works because Church numerals apply `successor` n times to `zero`. By chaining two folds, we get `successor^(a+b)(zero)` without any explicit recursion.

### Pattern 3: Semigroup Abstraction (Multiple Algebras per Type)

A single type can participate in multiple semigroups without newtypes or wrappers. Each semigroup pairs the type with a specific binary operation:

```yaml
# Abstract interface
Semigroup:
  element_type: {}
  Combine:
    left: {}
    right: {}
    result: {}

# Nat participates in TWO semigroups:
NatAddSemigroup:
  - [abstract, Semigroup]
  - element_type:
      - [types, Nat]
    Combine:
      left:
        - [types, Nat]
      right:
        - [types, Nat]
      result:
        - [nat, arithmetic, NatAdd]
        - augend:
            - [NatAddSemigroup, [Combine, left]]
          addend:
            - [NatAddSemigroup, [Combine, right]]

NatMultiplySemigroup:
  - [abstract, Semigroup]
  - element_type:
      - [types, Nat]               # Same type, different operation
    Combine:
      left:
        - [types, Nat]
      right:
        - [types, Nat]
      result:
        - [nat, arithmetic, NatMultiply]
        - multiplicand:
            - [NatMultiplySemigroup, [Combine, left]]
          multiplier:
            - [NatMultiplySemigroup, [Combine, right]]
```

In Haskell, this requires `newtype` wrappers (`Sum`, `Product`). In MIXIN, the semigroup is a separate mixin that references the type — no wrapping needed.

### Pattern 4: Polymorphic Operations via Parametrization

Operations that work across types accept their type-specific behavior as a parameter:

```yaml
PolyEquality:
  equality_operator: {}        # Hole: accepts BooleanEquality, NatEquality, etc.
  left: {}
  right: {}
  result:
    - [algorithms, comparison, PolyEquality, equality_operator]
    - left:
        - [algorithms, comparison, PolyEquality, left]
      right:
        - [algorithms, comparison, PolyEquality, right]
```

Usage: compose `PolyEquality` with a concrete `equality_operator` to get type-specific equality without modifying `PolyEquality` itself.

### Pattern 5: Expression Problem Solution

New types and new operations are added independently via composition (`⊕`), without modifying existing code. See `tests/src/expression_problem.mixin.yaml` for the canonical demonstration:

- **Base**: expression types (Literal, Addition) + evaluation operation
- **WithDisplay**: new operation (display) for existing types
- **WithNegation**: new type (Negation) + both operations
- **Full**: `Base ⊕ WithDisplay ⊕ WithNegation` — free composition

### Limitations

- **Recursive definitions**: Self-referential operations (e.g., recursive equality for Nat, fold over lists) cause infinite evaluation trees during snapshot generation. Use the Church encoding fold pattern where possible. For truly recursive operations, fixpoint support or snapshot cycle detection is needed.
- **Placeholder implementations**: `NatEquality`, `BinNatEquality`, `BinNatAdd`, `BinNatMultiply` are currently stubs. They return constant values because their correct implementations require recursive definitions.
