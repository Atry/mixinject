## Git Workflow

### Code Rollback Policy

**NEVER** use `git checkout` to discard changes or revert files. Always use **named `git stash`** instead.

**Why this rule exists:**
- `git checkout` permanently destroys uncommitted work with no recovery option
- Named stashes preserve the context and allow recovery if needed
- Stash names document why changes were saved, making it easier to find and restore work later
- This enforces a "safety first" approach where you can always undo mistakes

**Correct workflow for reverting changes:**

```bash
# ✗ FORBIDDEN - Never use git checkout to discard changes
git checkout mixinv2/src/mixinv2
git checkout .

# ✓ REQUIRED - Use named git stash with descriptive message
git stash push -m "refactoring: move _outer_mixin to StaticScope - testing if failure exists before refactor"

# Later, if you need to restore the stashed changes:
git stash list  # Find your stash
git stash apply stash@{0}  # Restore without removing from stash
git stash pop stash@{0}    # Restore and remove from stash
```

**Stash naming convention:**

Use descriptive names that explain:
1. What changes were stashed
2. Why they were stashed (e.g., testing, comparing, temporary work)

Examples:
- `"refactoring: testing original behavior before applying changes"`
- `"experiment: trying alternative implementation approach"`
- `"backup: preserving working state before major refactor"`
- `"debugging: isolating issue by reverting recent changes"`

**Viewing and managing stashes:**

```bash
# List all stashes with names
git stash list

# Show what's in a specific stash
git stash show stash@{0}
git stash show -p stash@{0}  # Show full diff

# Drop a stash when you're sure you don't need it
git stash drop stash@{0}

# Clear all stashes (use with caution)
git stash clear
```

**Exception:**

The only acceptable use of `git checkout` is for switching branches:

```bash
# ✓ ACCEPTABLE - Switching branches
git checkout main
git checkout -b feature-branch

# But prefer git switch for clarity:
git switch main
git switch -c feature-branch
```

## Dependency Management

This project uses Nix + uv2nix for Python dependency management. **Do not** use `pip`.

### Adding/Managing Dependencies

```bash
direnv exec . uv add <package>
direnv exec . uv remove <package>
direnv exec . uv lock
```

> **IMPORTANT:** Do NOT run `uv sync`. This project uses Nix-managed virtual environments, and `uv sync` will interfere with it. Use `uv lock` to update the lockfile only.

### Why `direnv exec .` is Required

The project creates a development environment via Nix flake, and `direnv` is responsible for activating it. Directly calling `uv` or `python` in Claude Code may not correctly access the Nix-managed virtual environment, so `direnv exec .` is needed to ensure commands run in the correct environment.

> **Warning:** After updating dependencies (including changes to `flake.nix` or Python packages), you must use `direnv exec .` to access the new virtual environment. Without it, you will get the old/stale environment and the changes will not be available.

### Refreshing the Nix Development Environment

When `uv.lock` or `flake.nix` changes, `direnv` may still use a cached (stale) Nix development shell. Run `direnv reload` to force `nix-direnv` to re-evaluate the flake and rebuild the virtual environment:

```bash
direnv reload
```

This is necessary when you see errors caused by stale packages (e.g., plugin conflicts from outdated dependency versions).

## Python Coding Conventions

### Use `@dataclass` for Structured Data

**Do NOT** use `tuple`, `NamedTuple`, `dict`, `TypedDict`, or custom `__init__` for structured data. Use `@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)` instead:

```python
# ✗ BAD - tuple (no field names, positional access only)
def get_user() -> tuple[int, str, str]:
    return (1, "alice", "alice@example.com")
id, name, email = get_user()  # Easy to mix up order

# ✗ BAD - NamedTuple (immutable, no methods, limited functionality)
from typing import NamedTuple
class User(NamedTuple):
    id: int
    name: str
    email: str

# ✗ BAD - dict (no type safety, typo-prone keys)
def get_user() -> dict[str, Any]:
    return {"id": 1, "name": "alice", "email": "alice@example.com"}

# ✗ BAD - TypedDict (dict with types, but still stringly-typed keys)
from typing import TypedDict
class User(TypedDict):
    id: int
    name: str
    email: str

# ✗ BAD - custom __init__
class User:
    def __init__(self, id: int, name: str, email: str):
        self.id = id
        self.name = name
        self.email = email

# ✓ GOOD - dataclass with full options
from dataclasses import dataclass

@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class User:
    id: int
    name: str
    email: str
```

**Why `@dataclass` over alternatives:**
- **vs tuple**: Named fields, type hints, readable access (`user.name` vs `user[1]`)
- **vs NamedTuple**: Methods, `@cached_property`, inheritance, better tooling support
- **vs dict/TypedDict**: Attribute access, IDE autocomplete, no string key typos
- **vs custom `__init__`**: Less boilerplate, automatic `__repr__`, `__eq__`, etc.

**Why `kw_only=True`:**
- Forces keyword arguments, making code more readable: `Config(name="x", value=1)`
- Prevents positional argument errors when adding/reordering fields
- Self-documenting at call sites

**Why `slots=True`:**
- Memory efficiency: no `__dict__` per instance
- Faster attribute access
- Prevents accidental attribute creation

**Why `frozen=True`:**
- Immutability by default: prevents accidental mutation
- Makes instances hashable (can be used as dict keys or in sets)
- Thread-safe without locks

**Why `weakref_slot=True`:**
- Allows weak references to instances even with `slots=True`
- Enables garbage collection of cyclic references

**Exception: `frozen=False` with Cache Slots**

When using `slots=True` fields as internal cache (set via `setattr` after construction), `frozen=False` is allowed. Non-cache fields MUST have `Final` type hints:

```python
@dataclass(kw_only=True, slots=True, weakref_slot=True, eq=False)
class CachedScope:
    symbol: Final["MixinSymbol"]  # Non-cache: use Final
    _cached_child: object = field(init=False)  # Cache: set via setattr
```

**Note on `Final` type hints:**

Frozen dataclasses (`frozen=True`) already enforce runtime immutability, so `Final` type hints could be omitted:

```python
# ✓ GOOD - frozen dataclass without Final (frozen already ensures immutability)
@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class Config:
    name: str
    value: int

# ✗ UNNECESSARY - Final is redundant with frozen=True
@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class Config:
    name: Final[str]  # Redundant: frozen already prevents mutation
    value: Final[int]
```

### `@final` and `slots` Requirements for Dataclasses

**Rule 1: Never instantiate non-`@final` dataclasses.**

Non-`@final` dataclasses are abstract base classes meant for inheritance only. Direct instantiation is prohibited.

```python
# ✗ BAD - instantiating a non-@final dataclass
@dataclass(kw_only=True, eq=False)
class _BaseNode(ABC):
    name: str

node = _BaseNode(name="test")  # FORBIDDEN: _BaseNode is not @final

# ✓ GOOD - only instantiate @final dataclasses
@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, eq=False)
class LeafNode(_BaseNode):
    value: int

node = LeafNode(name="test", value=42)  # OK: LeafNode is @final
```

**Rule 2: All `@final` dataclasses MUST have `slots=True` and `weakref_slot=True`.**

```python
# ✗ BAD - @final dataclass without slots
@final
@dataclass(kw_only=True, frozen=True)
class Config:
    name: str

# ✓ GOOD - @final dataclass with slots=True and weakref_slot=True
@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class Config:
    name: str
```

**Rule 3: All non-`@final` dataclasses MUST NOT have `slots=True` or `weakref_slot=True`.**

This is because Python's `__slots__` does not support multiple inheritance when both parent classes have non-empty slots. Non-`@final` dataclasses are meant to be inherited, and adding slots would cause `TypeError: multiple bases have instance lay-out conflict`.

```python
# ✗ BAD - non-@final dataclass with slots (will break multiple inheritance)
@dataclass(kw_only=True, slots=True, weakref_slot=True, eq=False)
class _BaseMapping(ABC):
    data: dict[str, Any]

# ✓ GOOD - non-@final dataclass without slots
@dataclass(kw_only=True, eq=False)
class _BaseMapping(ABC):
    data: dict[str, Any]
```

**Using `@cached_property` with slots:**

When a `@final` dataclass needs `@cached_property`, inherit from `HasDict`:

```python
# ✓ GOOD - @final dataclass with @cached_property inherits HasDict
@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, eq=False)
class ComputedNode(HasDict, _BaseNode):
    raw_value: int

    @cached_property
    def computed_value(self) -> int:
        return self.raw_value * 2
```

For non-`@final` dataclasses that need `@cached_property` and will be combined with other classes via multiple inheritance, inherit from `HasDict` but omit `slots=True`:

```python
# ✓ GOOD - non-@final dataclass with @cached_property
@dataclass(kw_only=True, eq=False)
class _CachingBase(HasDict, ABC):
    source: str

    @cached_property
    def cached_result(self) -> bytes:
        return self.source.encode()
```

**Summary table:**

| Dataclass type | `@final` | `slots=True, weakref_slot=True` | Can instantiate? |
| -------------- | -------- | ------------------------------- | ---------------- |
| Concrete leaf  | Yes      | Required                        | Yes              |
| Abstract base  | No       | Forbidden                       | No               |


### Avoid `__all__` and Re-exports

**Do NOT** use `__all__` or re-export symbols from `__init__.py`. All imports MUST be direct and explicit:

```python
# ✗ BAD - re-exporting in __init__.py
# src/hpcnc/model/__init__.py
from hpcnc.model.loader import load_model
__all__ = ["load_model"]

# ✗ BAD - importing from package instead of module
from hpcnc.model import load_model

# ✓ GOOD - empty __init__.py (or only docstring)
# src/hpcnc/model/__init__.py
"""Model package."""

# ✓ GOOD - direct import from module
from hpcnc.model.loader import load_model
```

**Why avoid `__all__` and re-exports:**
- Better grep-ability and "find usages" accuracy
- Clearer dependency graph
- Avoids circular import issues common with `__init__.py` re-exports
- Makes it explicit where a symbol is actually defined
- Reduced boilerplate in `__init__.py` files

### Avoid Default Values - They Are Anti-patterns

**Do NOT** use default values for dataclass fields or function parameters unless the user explicitly requests it:

```python
# ✗ BAD - default values hide required parameters
@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class Config:
    name: str
    value: int = 0  # BAD: default value
    role: str = "user"  # BAD: default value

def save_state(data: bytes, role: str = "ai") -> None:  # BAD: default value
    ...

# ✓ GOOD - all parameters are explicit and required
@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class Config:
    name: str
    value: int
    role: str

def save_state(data: bytes, role: str) -> None:
    ...
```

**Why default values are anti-patterns:**
- They hide required information, making bugs silent instead of loud
- They create implicit assumptions that are easy to miss
- They make it easy to forget to pass important parameters
- They violate "explicit is better than implicit"
- They can lead to subtle bugs when the default is wrong for a particular use case

**When default values are acceptable:**
- Only when the user explicitly requests it
- When backward compatibility with existing APIs is required (user must confirm this need)
- Never use default values autonomously

**When custom `__init__` is acceptable:**
- Complex initialization logic that cannot be expressed with `__post_init__`
- Compatibility with existing APIs that require specific signatures
- Performance-critical code where dataclass overhead matters

### Prefer `@cached_property` over `__post_init__`

**Do NOT** use `__post_init__` for derived/computed values. Use `@cached_property` instead:

```python
# ✗ BAD - using __post_init__ for derived values
@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class Rectangle:
    width: float
    height: float
    area: float = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "area", self.width * self.height)

# ✓ GOOD - using @cached_property for derived values
from functools import cached_property

@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class Rectangle:
    width: float
    height: float

    @cached_property
    def area(self) -> float:
        return self.width * self.height
```

**Why `@cached_property` over `__post_init__`:**
- Lazy evaluation: computed only when accessed, not at construction time
- Clearer semantics: explicitly marks the value as derived, not a true field
- Better separation: keeps computation logic close to the property definition
- Avoids `field(init=False)` boilerplate and the confusion it causes
- More Pythonic: uses standard property pattern instead of dataclass-specific hook

**When `__post_init__` is acceptable:**
- Validation logic that must run at construction time
- Side effects that must occur during initialization (e.g., registering the instance)
- Transforming input values before storing (though consider `field` with converter instead)
- When the computed value is needed for `__hash__` or `__eq__` (with `frozen=True`)

### Prefer `tuple` over `list`

**Do NOT** use `list` unless mutation is required. Use `tuple` by default:

```python
# ✗ BAD - using list for immutable data
def get_colors() -> list[str]:
    return ["red", "green", "blue"]

# ✓ GOOD - using tuple for immutable data
def get_colors() -> tuple[str, ...]:
    return ("red", "green", "blue")
```

**When `list` is acceptable:**
- When you need to mutate the collection (append, extend, pop, etc.)
- When interfacing with APIs that specifically require `list`
- When building collections incrementally where mutation is truly necessary

### Prefer Comprehensions and Generators over `append`

**Do NOT** use `append` in a loop. Use comprehensions or generators instead:

```python
# ✗ BAD - using append in a loop
result = []
for item in items:
    if item.is_valid:
        result.append(item.value)

# ✓ GOOD - using list comprehension
result = [item.value for item in items if item.is_valid]

# ✓ GOOD - using generator expression (lazy evaluation)
result = (item.value for item in items if item.is_valid)

# ✓ GOOD - using tuple comprehension for immutable result
result = tuple(item.value for item in items if item.is_valid)
```

**Why avoid `append`:**
- Comprehensions are more readable and Pythonic
- Generators are memory-efficient for large datasets
- Comprehensions clearly express intent (transform + filter)
- `append` loops hide the pattern and are more verbose

**When `append` is acceptable:**
- Never is acceptable

### Self-Descriptive Variable Names

**Do NOT** use abbreviated variable names. All variable names MUST be self-descriptive and use complete words:

```python
# ✗ BAD - abbreviated variable names
fn = get_handler()
func = create_processor()
cb = on_complete
val = compute_result()
obj = create_instance()
res = fetch_data()
msg = format_output()
cfg = load_settings()
ctx = create_context()
params = get_parameters()
args = parse_arguments()
kwargs = extract_keyword_arguments()

# ✓ GOOD - self-descriptive variable names
handler = get_handler()
processor = create_processor()
on_complete_callback = on_complete
result = compute_result()
instance = create_instance()
response = fetch_data()
message = format_output()
configuration = load_settings()
context = create_context()
parameters = get_parameters()
arguments = parse_arguments()
keyword_arguments = extract_keyword_arguments()
```

**Common forbidden abbreviations:**
- `fn`, `func` → use `function`, `handler`, `callback`, or a domain-specific name
- `cb` → use `callback` or `on_xxx_callback`
- `val` → use `value`, `result`, or a domain-specific name
- `obj` → use `instance`, `object`, or a domain-specific name
- `res` → use `result`, `response`, or a domain-specific name
- `msg` → use `message`
- `cfg`, `conf` → use `configuration`, `config`, or `settings`
- `ctx` → use `context`
- `params` → use `parameters`
- `args` → use `arguments`
- `kwargs` → use `keyword_arguments`
- `idx` → use `index`
- `cnt` → use `count`
- `tmp` → use `temporary` or a more descriptive name
- `ret` → use `result` or `return_value`

**Why self-descriptive names matter:**
- Code is read far more often than it is written
- Abbreviations require mental translation and increase cognitive load
- Self-descriptive names make code self-documenting
- Reduces the need for comments explaining what variables hold
- Makes code review and debugging significantly easier

**When abbreviations are acceptable:**
- Standard loop variables like `i`, `j`, `k` for numeric indices in tight loops
- Well-established domain abbreviations (e.g., `url`, `html`, `json`, `id`)
- Never for function references, callbacks, or domain objects

### Mandatory `super()` with `@override`

**ALL** functions decorated with `@override` **MUST** call `super()`.

- **Never** override a concrete implementation without calling `super()`. Doing so often violates the **Liskov Substitution Principle (LSP)** by breaking the base class's established contract, side effects, or state management.
- **Special Case for `slots=True`**: When using `@dataclass(..., slots=True, ...)`, you **MUST** use the explicit 2-argument form of `super()`: `super(ClassName, self)`. Do **NOT** use the 0-argument `super()` or `super(__class__, self)`, as these can fail due to how Python reconstructs classes with slots.
- If the base class method is an `@abstractmethod` and you do **NOT** want to call `super()`, you **MUST NOT** use `@override`.
- Use `@override` strictly for chain-of-responsibility/extension patterns where you are augmenting base behavior.
- Do **NOT** use `@override` for simple interface implementations of abstract methods where the base implementation is empty or intended to be ignored.

```python
# ✗ BAD - replacing concrete implementation without super() (violates LSP)
class Extended(Base):
    @override
    def process(self):
        # Base.process code is ignored, contract might be broken
        self.new_logic()

# ✗ BAD - using 0-arg super with slots=True
@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class MyData(Base):
    @override
    def process(self):
        super().process()  # Might fail with slots=True

# ✓ GOOD - extending concrete implementation with super() (respects LSP)
class Extended(Base):
    @override
    def process(self):
        super().process()
        self.new_logic()

# ✓ GOOD - 2-arg super with literal class name for slots=True
@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class MyData(Base):
    @override
    def process(self):
        super(MyData, self).process()
        self.new_logic()

# ✓ GOOD - implementing abstract method WITHOUT @override (no super() needed)
class Concrete(Abstract):
    def do_something(self):
        self.perform_action()
```

**Why this rule exists:**
- **Liskov Substitution Principle (LSP):** Subtypes must be substitutable for their base types. Overriding a concrete method without calling `super()` risks breaking the invariant expectations of the base class.
- **Predictability:** Ensures that method resolution chains are never accidentally broken and that base class logic (initialization, registration, etc.) is always executed.
- **Clarity:** Clearly distinguishes between *implementing* an interface and *extending* existing behavior.

### Representing Optional/Absent Values: Anti-patterns and Correct Pattern

The following are all **anti-patterns** for representing optional or absent values:

```python
# ✗ BAD - Optional[Xxx] or Xxx | None
from typing import Optional

def get_user(id: int) -> Optional[User]:
    return users.get(id)

def get_user(id: int) -> User | None:
    return users.get(id)

# ✗ BAD - Singleton sentinel constants
MISSING = object()
NOT_FOUND = object()
SENTINEL = object()

def get_config(key: str) -> Config | type[SENTINEL]:
    return configs.get(key, SENTINEL)

# ✗ BAD - XxxState enum + Optional[Xxx] in separate fields
class ResourceState(Enum):
    NOT_STARTED = auto()
    RUNNING = auto()
    DESTROYED = auto()

@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class Container:
    state: ResourceState
    resource: Resource | None  # Can become inconsistent with state!

# Problem: Two separate fields can become inconsistent
# Even with frozen=True, creating new instances can have mismatched state/resource
```

**Why these are anti-patterns:**
- `Optional[Xxx]` and `Xxx | None` force null checks everywhere, hide design issues
- Singleton sentinels like `MISSING` describe absence, not behavior
- `XxxState` enum + `Optional[Xxx]` in separate fields can become inconsistent
- All violate "explicit is better than implicit"

**The correct pattern: `Xxx | XxxSentinel` (sentinel enum in union)**

```python
# ✓ GOOD - sentinel enum in union consolidates state and resource
class ResourceSentinel(Enum):
    NOT_STARTED = auto()  # Resource hasn't been created yet
    DESTROYED = auto()    # Resource was cleaned up

@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class Container:
    resource: Resource | ResourceSentinel  # Single field, always consistent

# Usage - create instances with the appropriate state
container = Container(resource=ResourceSentinel.NOT_STARTED)  # Before init
container = Container(resource=create_resource())              # After init
container = Container(resource=ResourceSentinel.DESTROYED)    # After cleanup

# Type-safe matching
match container.resource:
    case ResourceSentinel.NOT_STARTED:
        initialize()
    case ResourceSentinel.DESTROYED:
        raise RuntimeError("Resource already destroyed")
    case Resource() as res:
        use(res)
```

**Why `Xxx | XxxSentinel` is good:**
- Single field ensures state and resource are always consistent
- No way to have inconsistent state (e.g., `state=DESTROYED` while `resource` still holds object)
- Type checker enforces exhaustive matching
- Self-documenting: the type annotation tells the full story
- Sentinel enum values describe *behavior* (NOT_STARTED, DESTROYED) not just absence
- Conceptually similar to Java's checked exceptions or Rust's `Result<T, E>`—the sentinel is a typed error channel in the return type that callers must handle

**The most common correct approach: immutable required fields**

In most cases, the simplest way to avoid `Optional` and `| None` is to make fields immutable and required:

```python
# ✓ GOOD - immutable required fields (best design in most cases)
@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class User:
    id: int        # Required, never None
    name: str      # Required, never None
    email: str     # Required, never None

# ✓ GOOD - if a field is truly optional, ask: should it be a separate type?
@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class BasicUser:
    id: int
    name: str

@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class VerifiedUser:
    id: int
    name: str
    email: str     # Only verified users have email
```

**Other correct approaches:**

```python
# ✓ GOOD - raise exceptions for "not found" cases
def get_user(id: int) -> User:
    if id not in users:
        raise KeyError(f"User {id} not found")
    return users[id]

# ✓ GOOD - behavior enum as return type (not paired with Optional data)
class ValidationResult(Enum):
    VALID = auto()
    INVALID_FORMAT = auto()
    EXPIRED = auto()
    REVOKED = auto()

def validate(token: str) -> ValidationResult:
    ...  # Returns result directly, no Optional pairing

# ✓ GOOD - policy enum controls behavior (not paired with Optional)
class CachePolicy(Enum):
    USE_CACHED = auto()
    FORCE_REFRESH = auto()
    STALE_IF_ERROR = auto()

def fetch(url: str, policy: CachePolicy) -> Response:
    ...  # Policy controls behavior
```

**When `Optional` or `| None` is acceptable:**
- Only when the user explicitly requests it
- Never use it autonomously

## MIXINv2 Coding Conventions

**Terminology note:** This project previously used the terms "mixin", "union", and "overlay". The language has been renamed to **MIXINv2**. Legacy references to "mixin", "union", or "overlay" in code, comments, or documentation refer to MIXINv2 concepts.

MIXINv2 adopts C#-like naming conventions. The UpperCamelCase/lowerCamelCase distinction is not merely stylistic — it carries semantic meaning for the totality checker: UpperCamelCase symbols are **scopes** (instantiable at runtime), while lowerCamelCase symbols are written as if they are **resources** (lazily evaluated values, no new UpperCamelCase children defined within them). This naming convention enables automatic totality verification without manual proofs (see `mixin_totality.tex`). Note that the scope/resource distinction is a design intent, not yet enforced by the compiler — currently all symbols compile to scopes regardless of casing.

### Naming Convention Summary

| Element                             | Casing         | Examples                                 | C# Analogy          | Math Analogy                    |
| ----------------------------------- | -------------- | ---------------------------------------- | ------------------- | ------------------------------- |
| namespace                           | UpperCamelCase | `Builtin`                                | namespace           | category / multi-sorted algebra |
| sort (class)                        | UpperCamelCase | `Nat`, `Boolean`, `BinNat`               | class               | sort (carrier set)              |
| algebraic structure (partial class) | UpperCamelCase | `NatPlus`, `BooleanAnd`                  | partial class       | endomorphism (Sort → Sort)      |
| category                            | UpperCamelCase | `NatEquality`, `BinNatEquality`          | —                   | morphism (Sort₁ → Sort₂)        |
| entity                              | UpperCamelCase | `Zero`, `Successor`, `True`, `False`     | —                   | element of a sort               |
| nested class/method                 | UpperCamelCase | `Visitor`, `Plus`, `Equal`, `And`, `Or`  | method/nested class | —                               |
| field                               | lowerCamelCase | `predecessor`, `addend`, `sum`           | field               | —                               |
| parameter                           | lowerCamelCase | `addend`, `other`, `operand0`            | parameter           | —                               |
| private member                      | `_` prefix     | `_increasedAddend`, `_recursiveAddition` | `private`           | —                               |

### Namespace (UpperCamelCase)

Borrowed from C#. A namespace corresponds to a **category** (or equivalently, a **multi-sorted algebra**). It contains sorts, algebraic structures, and categories as its members.

Example: `Builtin` is a namespace containing sorts (`Nat`, `Boolean`, `BinNat`), algebraic structures (`NatPlus`, `BooleanNegation`), and categories (`NatEquality`, `BinNatEquality`).

### Sort / Entity (UpperCamelCase)

A **sort** (mathematical term) is a carrier set — MIXINv2's equivalent of a C# class. Its data constructors are called **entities** (ECS term). These are two perspectives on the same concept: a sort is defined by its entities, and an entity belongs to a sort.

Sorts are defined using a `*Factory` + `Product` pattern: the factory contains `Product` (the abstract element type) and all entity constructors, while the sort name is aliased to `[*Factory, Product]`:

```yaml
NatFactory:        # Sort factory: natural numbers
  Product: []      # Abstract element type
  Zero:
    - [Product]
  Successor:
    - [Product]
    - predecessor: [Product]
Nat: [NatFactory, Product]   # Sort alias: Nat = NatFactory.Product

BooleanFactory:    # Sort factory: booleans
  Product: []
  "True": [Product]
  "False": [Product]
Boolean: [BooleanFactory, Product]
```

The `*Factory` indirection allows algebraic structures and categories to be composed onto the same factory without modifying the original sort definition. The sort alias (`Nat`, `Boolean`) provides a stable public name.

**Constructing a value** of a sort means inheriting one of its entity constructors and supplying the required fields. This is the constructor design pattern:

```yaml
# To construct a Successor wrapping some value n:
_wrappedN:
  - [Successor]          # inherit the Successor constructor
  - predecessor: [n]     # supply the required field

# To construct an Odd BinNat from an Even half:
_result:
  - [Odd]                # inherit the Odd constructor
  - half: [Even, ~, half]  # supply the required field
```

The result is then exposed via a projection field (e.g. `sum`, `decreased`, `increment`) so callers do not need to know which constructor was used — see Nested Class / Method below.

The entity **name** is its identity — it persists across compositions. Each individual **definition** of that entity within a category is a component. When categories are composed, components with the same entity name merge onto the same entity. For example, `NatData.Zero`, `NatVisitor.Zero`, and `NatPlus.Zero` are three separate components that all merge onto the entity `Zero`:

```yaml
# In NatData.oyaml: Zero is defined as a data variant
NatFactory:
  Product: []
  Zero:
    - [Product]
  Successor:
    - [Product]
    - predecessor: [Product]

# In NatPlus.oyaml: Zero gets a Plus component overlaid
- [NatData]
- NatFactory:
    Zero:
      Plus:
        addend: [Product]
        sum: [addend]   # 0 + m = m

# When composed, the entity Zero has both its original structure
# and the Plus behavior merged together
```

### Algebraic Structure — C# partial class (UpperCamelCase)

Borrowed from C#'s partial class concept. An algebraic structure adds operations to an existing sort, like a partial class adds methods to an existing class. It corresponds to an **endomorphism** (Sort → Sort) in multi-sorted algebra.

```yaml
# NatPlus.oyaml — adds Plus operation to Nat
- [NatData]              # Inherit the sort data definition
- NatFactory:            # Extend the factory
    Product:
      Plus:
        sum: [Product]   # Abstract type declaration
    Zero:
      Plus:
        addend: [Product]
        sum: [addend]    # 0 + m = m
    Successor:
      Plus:
        addend: [Product]
        sum: ...         # S(n) + m = S(n + m)
```

Key points:
- The file itself is a top-level list (no wrapping name like `NatPlus:`) — it is an anonymous category
- Inherits `[NatData]` (the category that defines `NatFactory`), not `[Nat]` (the alias `[NatFactory, Product]`)
- Parameters have type constraints: `addend: [Product]`, not `addend: []`

Examples: `NatPlus` (Nat × Nat → Nat), `BooleanNegation` (Boolean → Boolean, exposes `not` field), `BooleanAnd` (Boolean × Boolean → Boolean), `BooleanOr`, `BooleanEquality`, `BinNatPlus`, `BinNatIncrement`, `NatDecrement`, `BinNatDecrement`.

### Category — cross-sort morphism (UpperCamelCase)

A category encodes operations across different sorts (Sort₁ → Sort₂). Categories are defined as `.oyaml` files that inherit all relevant sort data files and extend the factory:

```yaml
# NatEquality.oyaml — encodes the morphism Nat × Nat → Boolean
- [NatVisitor]       # Inherit Nat visitor infrastructure
- NatFactory:        # Extend the Nat factory with equality
    - Product:
        Equal:
          other: [Product]
          equal: [NatEquality, ~, Boolean]   # Qualified this crosses sort boundary
      Zero:
        Equal:
          other: [Product]
          _OtherVisitor:
            - [other, Visitor]
            - VisitZero:
                equal: [NatEquality, ~, BooleanFactory, "True"]
              VisitSuccessor:
                equal: [NatEquality, ~, BooleanFactory, "False"]
              Visit:
                equal: [NatEquality, ~, Boolean]
          equal: [_OtherVisitor, Visit, equal]
      Successor:
        ...
- [BooleanData]      # Inherit Boolean sort data (output sort)
```

Key points:
- The file inherits all required input sort data (`[NatVisitor]`) and output sort data (`[BooleanData]`)
- Operations are defined within the input sort's factory (`NatFactory:`)
- Cross-sort references use qualified this: `[NatEquality, ~, Boolean]` navigates to the Boolean sort within the composed scope

Each `.oyaml` file is a **category** (multi-sorted algebra) that can be composed with other categories — a file may involve multiple sorts and multiple algebraic structures. This is how MIXINv2 natively solves the **expression problem**: composing `NatEquality` with `BooleanNegation` (by inheriting both) automatically gives the returned booleans a `not` field — without modifying either category.

### Abstract Factory Pattern with Declarations

MIXINv2 supports **abstract factories** through declarations. This pattern enables writing polymorphic code that works across multiple concrete factory types.

#### Declaring Abstract Projections (Slots)

A declaration declares an abstract slot with a type constraint, without providing a concrete implementation:

```yaml
# FibonacciFactory declares abstract Zero and One projections
FibonacciFactory:
  Zero: [Product]    # Abstract projection: expects a Product-typed value
  One: [Product]     # Abstract projection: expects a Product-typed value
  Product:
    Fibonacci:
      n: [Product]
      fibonacci: ...  # Uses Zero and One through lexical references
```

**Key insight:** `Zero: [Product]` is **NOT** a reference to a constructor. It is a **type-constrained slot** that concrete factories must satisfy.

#### Creating Abstract Base Classes

To make an abstract factory work with multiple concrete factories, use inheritance:

```yaml
# Step 1: Define abstract base in each concrete factory's data file
# In NatData.oyaml:
NumberFactory: []          # Abstract base factory
NatFactory:
  - [NumberFactory]        # NatFactory inherits from NumberFactory
  - Product: []
    Zero: [Product]
    Successor: [Product]

# In BinNatData.oyaml:
NumberFactory: []          # Same abstract base
BinNatFactory:
  - [NumberFactory]        # BinNatFactory inherits from NumberFactory
  - Product: []
    Zero: [Product]
    Even: [Product]
    Odd: [Product]
```

Now `NumberFactory` is a common base class that both `NatFactory` and `BinNatFactory` inherit from. This enables polymorphic composition.

#### Implementing Polymorphic Operations

Once the abstract base exists, you can write operations that work for **any** factory inheriting from `NumberFactory`:

```yaml
# NumberIsZero.oyaml — works for both Nat and BinNat
- NumberFactory:
    Zero: [Product]        # Declare abstract Zero projection (satisfied by concrete factories)
    Product:
      Equal:
        other: [Product]   # Declare abstract Equal operation (provided by NatEquality/BinNatEquality)
        equal: [NumberIsZero, ~, Boolean]  # equal is inherited from composed categories
      IsZero:
        _equalZero:
          - [Equal]        # Use abstract Equal operation
          - other: [Zero]  # Use abstract Zero projection (lexical reference)
        isZero: [_equalZero, equal]
- [Builtin, BooleanData]
```

**How this works:**
- `NumberFactory.Zero` is a declaration for lexical references within `NumberIsZero.oyaml`
- When composed with `NatFactory`, `[Zero]` resolves to `NatFactory.Zero` (the Nat constructor)
- When composed with `BinNatFactory`, `[Zero]` resolves to `BinNatFactory.Zero` (the BinNat constructor)
- `Equal` is an abstract operation that concrete factories must provide (via NatEquality/BinNatEquality)

#### Pattern Summary

1. **Define abstract base class** in each concrete factory's data file:
   ```yaml
   AbstractFactory: []
   ConcreteFactory:
     - [AbstractFactory]
   ```

2. **Declare abstract projections** with type constraints:
   ```yaml
   AbstractFactory:
     Zero: [Product]   # Abstract projection (slot)
   ```

3. **Implement polymorphic operations** using lexical references to abstract projections:
   ```yaml
   - AbstractFactory:
       Product:
         Operation:
           result: [Zero]  # Lexical reference resolves polymorphically
   ```

4. **Compose with concrete factories** through inheritance:
   ```yaml
   - [Builtin, NumberIsZero]   # Polymorphic operation
   - [Builtin, NatEquality]    # Concrete factory: works with Nat
   ```

### Nested Class / Method (UpperCamelCase)

Prefer **nouns and adjectives** over verbs to reflect MIXINv2's declarative nature:

```yaml
# ✓ GOOD - nouns and adjectives (declarative)
Visitor:
Visit:      # OK in Visitor pattern: "Visit" is a well-known noun in this context
Plus:
Addition:
Equal:
Negation:
And:
Or:

# ✗ BAD - verbs (imperative)
Add:
Negate:
Compare:
```

A nested class should expose its result as a **projection field** rather than directly inheriting a constructor. Callers read the result through the field; they should not need to know which constructor was used internally:

```yaml
# ✓ GOOD - Plus exposes result via projection field `sum: [Product]`
# Callers use ANF style: bind a temporary variable to Plus, then read sum from it
#   _addition:
#     - [someNat, Plus]
#     - addend: [otherNat]
#   result: [_addition, sum]
Product:
  Plus:
    sum: [Product]    # projection field: abstract result type
Zero:
  Plus:
    addend: [Product]
    sum: [addend]     # Zero + m = m, result is m directly
Successor:
  Plus:
    addend: [Product]
    sum: ...          # S(n) + m = S(n+m), result is a Successor

# ✗ BAD - directly inheriting a constructor leaks implementation details
# Callers would need to know the result is specifically a Successor
Successor:
  Plus:
    - addend: [Product]
    - [Successor]
    - predecessor: ...  # caller must navigate .predecessor, not .sum
```

### Field (lowerCamelCase)

Fields hold values within a class. The compiler currently does not treat fields specially, but they will be compiled to `@resource` in the future — meaning they are lazily evaluated and each value is computed at most once.

```yaml
Successor:
  predecessor: [Product]    # field: lowerCamelCase

Zero:
  Plus:
    addend: [Product]       # parameter: lowerCamelCase
    sum: [addend]           # field: lowerCamelCase
```

### Parameter (lowerCamelCase)

External inputs to operations, declared with a type reference to indicate they must be provided at instantiation time:

```yaml
Plus:
  addend: [Product]     # parameter: must be provided, typed as Product
  sum: [addend]         # field: computed from parameter

Equal:
  other: [Product]      # parameter: must be provided, typed as Product
  equal: [other]        # field: computed from parameter
```

### Private Members (Underscore Prefix)

Underscore prefix denotes private implementation details — intermediate computations not part of the public API.

**Naming rule for private members:** A resource (lowerCamelCase) **can contain** nested scopes via inheritance, but **cannot define** new nested scopes. If a symbol defines new UpperCamelCase children, it must itself be UpperCamelCase — even if private:

```yaml
Successor:
  Equal:
    other: [Product]

    # ✓ GOOD - lowerCamelCase: inherits [Successor] but only provides
    # lowerCamelCase fields (no new scope definitions)
    _increasedAddend:
      - [Successor]
      - predecessor: [addend]

    # ✓ GOOD - UpperCamelCase: defines new nested scopes
    # (VisitZero, VisitSuccessor, Visit are new scope definitions)
    _OtherVisitor:
      - [other, Visitor]
      - VisitZero:
            equal: [NatEquality, ~, "False"]
          VisitSuccessor:
            equal: [_recursiveEquality, equal]
          Visit:
            equal: [NatEquality, ~, Boolean]

    # ✗ BAD - lowerCamelCase but defines new scopes
    _otherVisitor:
      - [other, Visitor]
      - VisitZero:            # Defines a new scope → parent must be UpperCamelCase
            equal: ...

    equal: [_OtherVisitor, Visit, equal]
```

The distinction: `_increasedAddend` is lowerCamelCase because it only **contains** a Successor scope (via inheritance `- [Successor]`) and provides field values (`predecessor: [addend]`). `_OtherVisitor` is UpperCamelCase because it **defines** new nested scopes (`VisitZero`, `VisitSuccessor`, `Visit`).

### References: Lexical vs Qualified This

MIXINv2 provides two kinds of references for navigating the scope hierarchy:

#### 1. Lexical Reference `[Symbol]`

A **lexical reference** searches for a symbol in the current lexical scope (the file's static structure).

**Critical constraint:** Lexical references **cannot** access inherited properties (symbols introduced through inheritance).

```yaml
# ✓ GOOD - lexical reference to own property
NumberFactory:
  Zero: [Product]          # Own property: defined in this file
  Product:
    IsZero:
      _equalZero:
        - [Equal]           # Own property: defined in this file
        - other: [Zero]     # Own property: defined in this file
      isZero: [_equalZero, equal]
```

**When lexical references work:**
- Accessing sibling entities or nested scopes defined locally
- Simple, direct lookups within the mixin's own definitions, not inherited ones

#### 2. Qualified This Reference `[ScopeName, ~, path...]`

A **qualified this reference** (essentially "qualified super") navigates through the runtime composition graph to access **inherited properties** — symbols not defined in the current file but available through composition.

**Two key motivations for qualified this:**

1. **Bypass variable shadowing** (lexical scope issue)
2. **Access non-own properties** (properties inherited through composition)

```yaml
# Example: Accessing inherited Boolean from composed BooleanData
- NumberFactory:
    Product:
      Equal:
        equal: [NumberIsZero, ~, Boolean]  # Qualified this: Boolean is inherited, not own
- [Builtin, BooleanData]  # BooleanData provides the Boolean definition
```

**Variable shadowing example (from NatEquality.oyaml):**

```yaml
Equal:
  other:                   # Parameter 'other' in outer scope
    - [Product]
    - predecessor: [Product]
  _recursiveEquality:
    - [Successor, ~, predecessor, Equal]
    - other: [Equal, ~, other, predecessor]  # Defining field 'other'
    #         ^^^^^^^^^^^^^^^^^^
    #         Qualified this to access outer 'other' parameter,
    #         not the 'other:' field being defined here
```

Without qualified this, `[other]` in a lexical reference would be ambiguous:
- Does it refer to the outer `other` parameter?
- Or the `other:` field being defined on this line?

Using `[Equal, ~, other, predecessor]` explicitly navigates from `Equal` scope to the `other` parameter (bypassing the local `other:` being defined), then accesses its `predecessor` field.

**Common patterns:**

```yaml
# Accessing inherited property from composed category
NatFactory:
  Product:
    Equal:
      equal: [NatEquality, ~, Boolean]  # Boolean comes from composed BooleanData
      #       ^^^^^^^^^^^^ scope name in composed result
      #                     ^^^^^^^ inherited property

# Cross-file constructor reference
NatFactory:
  Zero:
    Equal:
      _OtherVisitor:
        VisitZero:
          equal: [NatEquality, ~, BooleanFactory, "True"]  # BooleanFactory.True is inherited
          #       ^^^^^^^^^^^^ scope name
          #                     ^^^^^^^^^^^^^^^ ^^^^^^ path to inherited entity
```

**When to use qualified this:**
- Accessing properties inherited through composition (non-own properties)
- Bypassing variable shadowing in lexical scope
- Cross-file references where the target is not defined in the current file

**Common mistakes:**

```yaml
# ✗ BAD - using file name instead of factory name
IsZero:
  _equalZero:
    - [Equal]
    - other: [NumberIsZero, ~, Zero]  # WRONG: NumberIsZero is file name, not a factory
    #        ^^^^^^^^^^^^^ File name, not a runtime scope instance

# ✓ GOOD - using lexical reference for own property (simplest)
IsZero:
  _equalZero:
    - [Equal]
    - other: [Zero]  # BEST: lexical reference to own property (defined in this file)

# ✓ GOOD - qualified this for inherited property
IsZero:
  equal: [NumberIsZero, ~, Boolean]  # Boolean is inherited from BooleanData, not own
```

#### Rule: Lexical for Own, Qualified This for Inherited

**Use lexical references `[Symbol]` for own properties (defined in current file).**

**Use qualified this `[Scope, ~, Symbol]` for inherited properties (from composed files).**

Lexical references are simpler but limited to own properties. Qualified this is required when accessing inherited properties or bypassing variable shadowing.

**Important:** Do not use an empty declaration `symbol: []` as a workaround to access inherited properties via lexical reference `[symbol]`. An empty declaration silently creates a new empty scope if the inherited property does not exist (e.g., the base scope was not composed), masking composition mistakes. Qualified this fails with an error in the same situation, providing fail-fast behavior.

```yaml
# ✗ BAD - empty declaration masks missing inherited property
RequestScope:
  - [ffi, HttpSendResponse]
  - written: []                    # Silently creates empty scope if HttpSendResponse is not composed
    response: [written]

# ✓ GOOD - qualified this fails loudly if inherited property is missing
RequestScope:
  - [ffi, HttpSendResponse]
  - response: [RequestScope, ~, written]  # Error if HttpSendResponse does not provide 'written'
```

### Known Limitations

#### oyaml files cannot be a bare scalar

An `.oyaml` file whose entire content is a single scalar value (string, number, etc.) is **not currently supported**. The top-level structure of an `.oyaml` file must be a mapping (dict) or a list.

```yaml
# ✗ NOT SUPPORTED - entire file is a bare scalar
"Hello World"

# ✗ NOT SUPPORTED - entire file is a bare number
42

# ✓ SUPPORTED - top-level mapping
greeting: "Hello World"
count: 42

# ✓ SUPPORTED - top-level list (anonymous category)
- [SomeInheritance]
- key: value
```

This is a known bug tracked for future fix. When you need to provide a scalar configuration value via oyaml, wrap it in a mapping instead of using a bare scalar file.


## Nix Commands

When running Nix commands (e.g., `nix build`, `nix develop`, `nix flake update`), always use `--print-build-logs` (or `-L`) to display build logs:

```bash
nix build --print-build-logs
nix develop -L
nix flake update --print-build-logs
```

This helps with debugging build failures and understanding what's happening during the build process.


### Jupyter Lab for MCP Server

This project includes a Jupyter Lab server that can be used with the `jupyter` MCP (Model Context Protocol) server for notebook-based debugging and development.

> **IMPORTANT:** Do NOT use Python command line with heredoc (e.g., `python << 'EOF'`) for temporary code execution or debugging. Instead, ALWAYS use the Jupyter MCP server to create and run code in `<your-file-name>.local.ipynb` notebooks. These local notebooks are gitignored and provide a better debugging experience with persistent state and output history.

**Starting Jupyter Lab:**

```bash
direnv exec . start-jupyter-lab
```

This command:
- Starts Jupyter Lab in a detached `screen` session, which can be connected by the `jupyter` MCP server tools
- Creates a session named `jupyter-<directory-name>` that persists in the background

**Token Management:**

- If `JUPYTER_TOKEN` is not set, the script generates a secure random token
- The token is automatically saved to [.env](.env) to maintain consistency across sessions
- Subsequent launches will reuse the same token from [.env](.env)

**Session Management:**

The Jupyter Lab server runs in a detached `screen` session, which means:
- It continues running in the background after the command completes
- You can check the logs by enabling logging and tailing the file `%S.%n.local.screenlog`

**Restarting Jupyter Lab:**

To stop an existing Jupyter Lab server and start a new one:

```bash
# Stop the current Jupyter Lab server
direnv exec . jupyter server stop

# IMPORTANT: Do NOT terminate the Jupyter Lab server with abrupt kill commands such as `kill`, `pkill`, or `screen -X quit` unless explicitly requested.

# Start a new Jupyter Lab server
direnv exec . start-jupyter-lab
```

This is necessary when dependencies are updated (e.g., [flake.lock](flake.lock), [uv.lock](uv.lock)) and you need the Jupyter Lab server to use the new environment with updated packages.

**Usage with MCP:**

Once Jupyter Lab is running, the `jupyter` MCP server tools can connect to it for:
- Creating and managing notebooks programmatically
- Executing code cells for debugging
- Reading notebook outputs and results

## IMPORTANT: ⚔️ Offensive Programming

This project follows **Offensive Programming** principles: fail fast, fail loud, and let bugs crash the program immediately rather than hiding them. The goal is to make bugs impossible to ignore by crashing early with clear error messages.

1. **Crash on postcondition violations**: If function A calls function B, function A MUST `assert` every condition it relies on about B's return value (type/shape/non-empty/key presence/order, etc.). If the assertion fails, let the program crash—this exposes bugs in B immediately.
2. **Crash on invalid input**: Invalid external/user input MUST raise `ValueError("reason")` immediately. No sentinel returns, no fallback values—crash and tell the caller exactly what went wrong.
3. **No error recovery unless explicitly requested**: Do NOT add any `try/except` unless the user explicitly asks for it. Error recovery hides bugs and makes debugging harder.
4. **Let it crash**: Never use `try/except` to hide, swallow, or silence errors. If something fails, let the crash expose the root cause. Suppressing errors is the enemy of bug discovery.
5. **Ask before adding error handling**: If you believe an error is genuinely recoverable and a `try/except` handler is needed, STOP and ask the user for confirmation—do not add it autonomously.
6. **Self-explanatory code over comments**: Replace comments with self-documenting code using `logger.debug()` statements or extracting logic into well-named functions that explain the intent (e.g., `def perform_initialization(): ...` instead of `# perform initialization`).
7. **Crash on wrong assumptions**: NEVER use hardcoded indices like `my_sequence[0]`. If a sequence contains exactly one element, use unpacking syntax `single_item, = my_sequence` instead of indexing. This crashes immediately if the assumption is violated, exposing the bug.

**Why Offensive Programming?**
- Silent failures are worse than crashes—they corrupt data and hide bugs
- A crash with a stack trace tells you exactly where the bug is
- "Fail fast" means bugs are caught in development, not production
- Recovery code often masks the real problem and introduces new bugs

Do NOT write redundant asserts for facts already guaranteed by parameter or return type annotations (e.g. avoid `assert isinstance(count, int)` when the signature declares `count: int`). Focus asserts on semantic invariants not encoded in the static types (non-empty, ordering, relationships between values, normalized ranges, cross-field consistency, etc.).

Examples:

```python
def fetch_profile(repo, user_id: str):
    # Crash immediately if user_id is invalid—don't return None or a default
    if not user_id:
        raise ValueError("user_id must be non-empty")
    profile = repo.get(user_id)
    # Crash if repo.get violates its contract—expose the bug in repo
    assert profile is not None, "repo.get must return a profile object"
    assert profile.id == user_id, f"Expected id {user_id}, got {profile.id}"
    return profile

def process_results(results: list[str]):
    # ✅ CORRECT: Unpacking crashes if assumption is wrong—bug exposed immediately
    single_result, = results
    return single_result.upper()

    # ❌ WRONG: Hardcoded index silently succeeds with multiple elements—bug hidden
    # return results[0].upper()

# ❌ FORBIDDEN (suppresses root cause, hides bugs):
# try:
#     data = parse(raw)
# except Exception:
#     data = None  # Bug is now invisible—NEVER do this
```

Use `assert` for internal invariants about trusted code paths; use `ValueError` for invalid caller/user inputs. Let the program crash—crashes are your friend in finding bugs.

### Exceptions with Special Semantics

Some Python exceptions have **special meanings** tied to specific dunder methods or protocols. These exceptions MUST NOT propagate through unrelated methods—they must be caught and converted to appropriate exceptions.

| Exception        | Semantic Owner                                 | Why It's Special                                     |
| ---------------- | ---------------------------------------------- | ---------------------------------------------------- |
| `KeyError`       | `__getitem__`, `__delitem__`                   | Caught by `__contains__`, signals "key not found"    |
| `IndexError`     | `__getitem__` (sequences)                      | Terminates `for` loops, signals "index out of range" |
| `StopIteration`  | `__next__`                                     | Terminates `for` loops, signals iterator exhaustion  |
| `AttributeError` | `__getattr__`, `__getattribute__`, descriptors | Caught by `hasattr()`, `getattr()` with default      |
| `GeneratorExit`  | Generators                                     | Special generator lifecycle, should not escape       |

**Why this matters:**

These exceptions are caught by Python's runtime in specific contexts:
- `hasattr(obj, 'x')` catches `AttributeError` → wrong escape causes incorrect `hasattr()` results
- `for x in seq` catches `IndexError`/`StopIteration` → wrong escape terminates loops early
- `x in mapping` may catch `KeyError` → wrong escape causes incorrect containment checks

**Example: KeyError**

```python
# ✗ BAD - KeyError escaping from non-__getitem__ method
def resolve_path(self, path: tuple[str, ...]) -> Symbol:
    current = self
    for part in path:
        current = current[part]  # KeyError escapes if part not found
    return current

# ✓ GOOD - Use .get() and raise descriptive error
def resolve_path(self, path: tuple[str, ...]) -> Symbol:
    current = self
    for part in path:
        child = current.get(part)
        if child is None:
            raise ValueError(
                f"Cannot navigate path {path!r}: '{current.key}' has no child '{part}'"
            )
        current = child
    return current
```

**Example: AttributeError**

```python
# ✗ BAD - AttributeError escaping from property (breaks hasattr)
@property
def config(self) -> Config:
    return self.parent.settings  # AttributeError if parent has no settings
    # hasattr(obj, 'config') now returns False incorrectly!

# ✓ GOOD - Convert to descriptive error
@property
def config(self) -> Config:
    parent = self.parent
    if not hasattr(parent, 'settings'):
        raise ValueError(f"Parent {parent!r} has no settings")
    return parent.settings
```

**Example: StopIteration**

```python
# ✗ BAD - StopIteration escaping from non-iterator (Python 3.7+ converts to RuntimeError)
def get_first(items: Iterable[T]) -> T:
    return next(iter(items))  # StopIteration if empty

# ✓ GOOD - Handle explicitly
def get_first(items: Iterable[T]) -> T:
    iterator = iter(items)
    try:
        return next(iterator)
    except StopIteration:
        raise ValueError("Cannot get first item: iterable is empty") from None
```

**Rule:** If you call code that may raise these special exceptions, you MUST either:
1. Use safe alternatives (`.get()`, `hasattr()`, `next(iter, default)`)
2. Catch and convert to an appropriate exception with context


## Handling Test Failures After Code Changes

When code modifications cause tests to fail, consider **three possible scenarios** before making any changes:

### 1. Tests Need to Be Updated

The test expectations are outdated and need to reflect the new, correct behavior.

**When this applies:**
- The code change was intentional and the new behavior is correct
- The test was written for the old behavior that is no longer valid
- The test assertions need to match the new expected output

**Action:** Update the test to reflect the new behavior.

### 2. Source Code Has a Trivial Bug

There's a simple, obvious bug in the source code that can be fixed without changing the design.

**When this applies:**
- The fix is a typo, missing import, or obvious logic error
- The fix does not change the intended behavior or design
- The fix is unambiguous and doesn't require design decisions

**Action:** Fix the trivial bug in the source code.

### 3. Source Code Design Conflicts with Test Assumptions

The source code's design and the test's assumptions are fundamentally incompatible.

**When this applies:**
- Fixing the test failure would require changing the source code's behavior
- The "fix" would involve adding workarounds, special cases, or design changes
- You are uncertain whether the source code or the test is "correct"

**Action:** **STOP and ask the user.** Do NOT autonomously modify source code behavior.

### 🎉 Discovering Design Conflicts is Valuable

When tests fail and reveal a conflict between source code design and test assumptions, **this is a good thing**. It proves the value of tests:

- Tests caught a real design issue that would otherwise go unnoticed
- The conflict forces explicit design decisions rather than implicit assumptions
- This is exactly what tests are for: exposing problems early

**Do NOT view this as an obstacle to overcome.** View it as valuable information that requires human judgment.

### ☠️ Autonomous Workarounds Are Extremely Harmful

Adding workarounds **without user confirmation** to make tests pass is **catastrophically bad**:

- Workarounds hide the real problem instead of solving it
- They introduce behavior changes outside of the planned design
- They create technical debt that compounds over time
- They break the trust relationship between tests and implementation
- A passing test suite becomes meaningless if tests pass due to workarounds

**Examples of forbidden autonomous workarounds:**
- Adding method overrides (like `__contains__`) just to make tests pass
- Adding special case handling for specific test scenarios
- Modifying return values to match test expectations without understanding why
- Catching and suppressing exceptions that tests don't expect

**Workarounds are acceptable ONLY when explicitly requested by the user.** The user may have valid reasons to accept a workaround as a temporary or permanent solution. But this decision belongs to the user, not to the assistant.

**The correct response to a design conflict is ALWAYS to stop and ask.**

### ⚠️ Critical Rule

**Source code behavior changes MUST only come from:**
1. The original plan approved by the user
2. Explicit user requests

**Source code behavior changes MUST NEVER come from:**
- Attempts to make tests pass
- Assumptions about what the "correct" behavior should be

If you cannot fix a test failure through trivial bug fixes or test updates, you MUST ask the user for guidance. Do NOT add workarounds, override methods, or change behavior just to make tests pass.

```python
# ✗ FORBIDDEN - Adding __contains__ override just to fix a test
def __contains__(self, key: object) -> bool:
    # This changes the class's behavior beyond the original plan
    return any(k == key for k in self)

# ✗ FORBIDDEN - Adding special case handling to pass tests
if isinstance(result, SyntheticSymbol):
    # Workaround to make test pass - violates design
    result = create_workaround_symbol()

# ✓ CORRECT - Ask the user when design conflicts with tests
# "The test expects X but the code does Y. Should I:
#  (a) Update the test to expect Y, or
#  (b) Change the code design to produce X?"
```

## Logging Best Practices

### Use `logging`, NOT `print`

**Do NOT** use `print()` for output in application code. Use `logging` instead:

### Adding Debug Logs

Use `%(funcName)s` in the log format to automatically include function names. Do not manually prefix log messages with function names.

Use named placeholders instead of positional arguments for better readability:

```python
# Good - named placeholders
logger.debug("bytes=%(bytes)d preview=%(preview)r", {"bytes": len(data), "preview": data[:100]})

# Bad - positional arguments
logger.debug("read returned %d bytes: %r", len(data), data[:100])

# Bad - redundant manual prefix
logger.debug("[read] read returned %d bytes: %r", len(data), data[:100])
```

## Snapshot Testing with Syrupy

1. Do not assert variables against hard-coded literal constants directly; instead assert them against a Syrupy snapshot and always supply an explicit snapshot name via name="<descriptive_name>" to keep snapshots readable.
2. When a Syrupy snapshot assertion fails, first re-run the test suite with --snapshot-update to regenerate the snapshot, then you MUST review the updated snapshot contents to confirm they match the intended change, then re-run the tests without --snapshot-update to ensure the updated snapshot passes reproducibly.
3. Do not use a snapshot when comparing a value to another variable produced within the same test (variable-to-variable logic) or when asserting a trivially obvious outcome such as a boolean success flag that should simply be True.

```python
from syrupy.assertion import SnapshotAssertion

def test_compute(snapshot: SnapshotAssertion):
	result = expensive_or_complex_compute()
	# Instead of: assert result == {"status": "ok", "value": 3}
	assert result == snapshot(name="compute_result")
```


## LaTeX Style (inheritance-calculus paper)

### Heading capitalization

- `\section` and `\subsection`: **Title Case** (capitalize all major words; lowercase articles, prepositions, and conjunctions unless they are the first word).
- `\paragraph`: **Sentence case** (capitalize only the first word and proper nouns).

### No trailing periods in headings

`\paragraph` headings must **not** end with a period:

```latex
% ✗ BAD
\paragraph{Church-encoded Nats are tries.}

% ✓ GOOD
\paragraph{Church-encoded Nats are tries}
```

### Building the paper

The paper entry points are `preprint.tex` and `submission.tex`, which `\input` the shared body `inheritance-calculus.tex`. Build via:

```bash
cd inheritance-calculus && direnv exec . latexmk -pdf preprint.tex
```

Do **not** run `latexmk` directly on `inheritance-calculus.tex` — it is a fragment without a `\documentclass`.

## Adding TeXLive Packages

TeXLive packages are declared in `modules/texlive.nix`. Note that package names in nixpkgs may differ from CTAN names (e.g., `zi4` is `inconsolata`, `newtxmath` is `newtx`).

## Naming Conventions

- **Do not use single-letter variable names.** Use descriptive names that convey the purpose of the variable.
- **Do not use abbreviated or truncated English words** (e.g., `expr` for `expression`, `env` for `environment`, `val` for `value`). Write out the full word. The fact that an abbreviation is widely used in the industry does not justify its use here.
- **Exception:** established notations that are part of a fixed formal system are permitted, but these are limited to very few cases (e.g., `T` for a type variable in a typing judgment, `Γ` for a typing context). When in doubt, spell it out.
