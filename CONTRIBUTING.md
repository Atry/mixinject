
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
    id: Final[int]
    name: Final[str]
    email: Final[str]
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

**Use `Final` for field-level type hints:**

```python
# ✓ GOOD - Final on field level
@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class Config:
    name: Final[str]
    value: Final[int]
```

**Why `Final` with `frozen=True`:**
- `frozen=True` enforces runtime immutability
- `Final` provides static type checking immutability guarantees
- Together they provide both runtime and compile-time safety

**IMPORTANT: All dataclass fields MUST be `Final` by default.**
- Do NOT create non-`Final` fields without explicit user approval
- If you need a mutable field, ask the user first and explain why
- This rule applies to ALL dataclass fields, including those with `field(default_factory=...)`


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
    name: Final[str]
    value: Final[int] = 0  # BAD: default value
    role: Final[str] = "user"  # BAD: default value

def save_state(data: bytes, role: str = "ai") -> None:  # BAD: default value
    ...

# ✓ GOOD - all parameters are explicit and required
@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class Config:
    name: Final[str]
    value: Final[int]
    role: Final[str]

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
    width: Final[float]
    height: Final[float]
    area: float = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "area", self.width * self.height)

# ✓ GOOD - using @cached_property for derived values
from functools import cached_property

@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class Rectangle:
    width: Final[float]
    height: Final[float]

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
    state: Final[ResourceState]
    resource: Final[Resource | None]  # Can become inconsistent with state!

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
    resource: Final[Resource | ResourceSentinel]  # Single field, always consistent

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

**The most common correct approach: immutable required fields**

In most cases, the simplest way to avoid `Optional` and `| None` is to make fields immutable and required:

```python
# ✓ GOOD - immutable required fields (best design in most cases)
@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class User:
    id: Final[int]        # Required, never None
    name: Final[str]      # Required, never None
    email: Final[str]     # Required, never None

# ✓ GOOD - if a field is truly optional, ask: should it be a separate type?
@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class BasicUser:
    id: Final[int]
    name: Final[str]

@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class VerifiedUser:
    id: Final[int]
    name: Final[str]
    email: Final[str]     # Only verified users have email
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

## IMPORTANT: 🛡️ Defensive Programming

1. Postconditions via assert: If function A calls function B, function A can `assert` every condition it relies on about B's return value (type/shape/non-empty/key presence/order, etc.).
2. Input errors raise ValueError: Invalid external/user input can raise `ValueError("reason")` immediately (no sentinel returns).
3. No try/except unless explicitly requested: Do NOT add any `try/except` unless the user explicitly asks for it.
4. Never suppress errors: Never use `try/except` to hide, swallow, or silence errors during debugging; always find and fix the root cause instead.
5. Confirm before recoverable handling: If you believe an error is genuinely recoverable and a `try/except` handler is needed, STOP and ask the user for confirmation—do not add it autonomously.
6. Self-explanatory code over comments: Replace comments with self-documenting code using `logger.debug()` statements or extracting logic into well-named functions that explain the intent (e.g., `def perform_initialization(): ...` instead of `# perform initialization`).
7. No hardcoded indices: NEVER use hardcoded indices like `my_sequence[0]`. If a sequence contains exactly one element, use unpacking syntax `single_item, = my_sequence` instead of indexing to make the single-element expectation explicit and fail fast if the assumption is violated.

Do NOT write redundant asserts for facts already guaranteed by parameter or return type annotations (e.g. avoid `assert isinstance(count, int)` when the signature declares `count: int`). Focus asserts on semantic invariants not encoded in the static types (non-empty, ordering, relationships between values, normalized ranges, cross-field consistency, etc.).

Examples:

```python
def fetch_profile(repo, user_id: str):
    if not user_id:
        raise ValueError("user_id must be non-empty")
    profile = repo.get(user_id)
    assert profile is not None, "repo.get must return a profile object"
    assert profile.id == user_id, f"Expected id {user_id}, got {profile.id}"
    return profile

def process_results(results: list[str]):
    # ✅ CORRECT: Unpacking makes single-element expectation explicit
    single_result, = results
    return single_result.upper()

    # ❌ WRONG: Hardcoded index silently succeeds with multiple elements
    # return results[0].upper()

# Forbidden (suppresses root cause):
# try:
#     data = parse(raw)
# except Exception:
#     data = None  # NEVER do this
```

Use `assert` for internal invariants about trusted code paths; use `ValueError` for invalid caller/user inputs. No other exception/handler policy changes are implied.
