"""Package/module-based equivalents of all code examples shown in README.md.

Each test mirrors a corresponding test in test_readme_examples.py, but uses
Python module files instead of @scope-decorated classes. The fixture package
lives in tests/fixtures/app_di/.

The DI semantics are identical — only the declaration style differs:
  @scope class SQLiteDatabase: ...   →   sqlite_database.py module
  @scope class UserRepository: ...   →   user_repository/ package
  nested @scope class RequestScope   →   request_scope/ subpackage
"""

import tempfile
import threading
import urllib.request
from pathlib import Path
from types import ModuleType

import pytest

import tests.fixtures.app_di as app_di
import tests.fixtures.app_di.eager_database as eager_database
import tests.fixtures.app_di.pragmas.base as pragma_base
import tests.fixtures.app_di.pragmas.foreign_keys as foreign_keys
import tests.fixtures.app_di.pragmas.user_version as user_version
import tests.fixtures.app_di.pragmas.wal_mode as wal_mode
import tests.fixtures.app_oyaml as app_oyaml

from overlay.language import extern, public, resource, scope
from overlay.language.mixin_directory import DirectoryMixinDefinition
from overlay.language.mixin_parser import OverlayFileScopeDefinition
from overlay.language.runtime import evaluate


# ---------------------------------------------------------------------------
# Step 1 – Define services (module equivalents)
# ---------------------------------------------------------------------------


class TestStep1ModuleServices:
    """Module/package equivalents of README Step 1 examples."""

    def test_extern_and_flat_composition(self) -> None:
        """step1_app composes sqlite_database + user_repository via @extend."""
        app = evaluate(app_di, modules_public=True).step1_app(
            database_path=":memory:",
        )
        assert app.user_count == 2
        app.connection.close()


# ---------------------------------------------------------------------------
# Step 2 – @patch and @merge (module equivalents)
# ---------------------------------------------------------------------------


class TestStep2ModulePatchAndMerge:
    """Module/package equivalents of README Step 2 examples."""

    def test_patch_overrides_resource(self) -> None:
        """wal_mode.py patches startup_pragmas defined in pragma_base.py."""
        root = evaluate(pragma_base, wal_mode, modules_public=True)
        assert "PRAGMA journal_mode=WAL" in root.startup_pragmas

    def test_merge_collects_patches_into_frozenset(self) -> None:
        """foreign_keys.py and wal_mode.py both patch startup_pragmas."""
        root = evaluate(pragma_base, wal_mode, foreign_keys, modules_public=True)
        assert root.startup_pragmas == frozenset(
            {"PRAGMA journal_mode=WAL", "PRAGMA foreign_keys=ON"}
        )

    def test_patch_with_dependency_injection(self) -> None:
        """user_version.py patch declares @extern schema_version."""
        app = evaluate(pragma_base, user_version, modules_public=True)(schema_version=3)
        assert app.startup_pragmas == frozenset({"PRAGMA user_version=3"})


# ---------------------------------------------------------------------------
# Step 3 – @eager (module equivalent)
# ---------------------------------------------------------------------------


class TestStep3ModuleEager:
    """Module/package equivalents of README Step 3 examples."""

    def test_eager_runs_schema_migration_at_startup(self) -> None:
        """eager_database.py: @eager @resource evaluated before evaluate() returns."""
        root = evaluate(eager_database, modules_public=True)
        tables = root.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        assert ("users",) in tables
        root.connection.close()


# ---------------------------------------------------------------------------
# Step 4 – App scope vs request scope (module equivalents)
# ---------------------------------------------------------------------------


class TestStep4ModuleHttpServer:
    """Module/package equivalents of README Step 4 examples."""

    def test_app_and_request_scope(self) -> None:
        """step4_app composes all four modules via @extend; request scopes union-mounted automatically."""
        app = evaluate(app_di, modules_public=True).step4_app(
            database_path=":memory:",
            host="127.0.0.1",
            port=0,
        )

        server = app.server
        server_thread = threading.Thread(target=server.handle_request, daemon=True)
        server_thread.start()

        assigned_port = server.server_address[1]
        response = urllib.request.urlopen(f"http://127.0.0.1:{assigned_port}/users/1")
        assert response.read() == b"total=2 current=alice"

        server_thread.join(timeout=2)
        server.server_close()
        app.connection.close()

    def test_request_scope_created_fresh_per_request(self) -> None:
        """Each call to request_scope(...) produces an independent InstanceScope."""
        app = evaluate(app_di, modules_public=True).step4_request_app(
            database_path=":memory:",
        )

        class FakeRequest:
            path = "/users/1"

        scope_a = app.request_scope(request=FakeRequest())
        scope_b = app.request_scope(request=FakeRequest())

        assert scope_a.current_user.user_id == 1
        assert scope_a.current_user.name == "alice"
        assert scope_b.current_user.user_id == 1
        assert scope_a is not scope_b

        app.connection.close()


class TestOyamlScopeClassComposition:
    """Tests oyaml scalar field values overriding @extern definitions
    inside a @scope class.
    """

    def test_scope_class_with_oyaml_scalar_fields(self) -> None:
        """Inherit a @scope class in oyaml and provide scalar field values."""
        module = ModuleType("remove_prefix_module")
        module.__name__ = "remove_prefix_module"

        @public
        @scope
        class RemovePrefix:
            @extern
            def this() -> str: ...

            @extern
            def prefix() -> str: ...

            @public
            @resource
            def prefix_removed(this: str, prefix: str) -> str:
                return this.removeprefix(prefix)

        module.RemovePrefix = RemovePrefix  # type: ignore[attr-defined]

        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "App.oyaml").write_text(
                "_greeting:\n"
                "  - [RemovePrefix]\n"
                '  - this: "Hello World"\n'
                '    prefix: "Hello "\n'
                "greeting: [_greeting, prefix_removed]\n"
            )

            directory_definition = DirectoryMixinDefinition(
                inherits=(),
                is_public=True,
                underlying=Path(tmpdir),
            )

            root = evaluate(module, directory_definition, modules_public=True)
            assert root.App.greeting == "World"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Step 4 – App scope vs request scope (oyaml equivalents)
# ---------------------------------------------------------------------------


class TestOyamlHttpApp:
    """Oyaml equivalents of README Step 4 examples.

    App.oyaml composes SQLiteDatabase + UserRepository + HttpHandlers +
    NetworkServer using inheritance lists.  The FFI layer lives in
    tests/fixtures/app_oyaml/__init__.py.
    """

    def test_oyaml_app_http_request(self) -> None:
        """app scope in App.oyaml serves correct response for GET /users/1."""
        root = evaluate(app_oyaml, modules_public=True)
        composed_app = root.App.app  # type: ignore[union-attr]

        server = composed_app.server
        server_thread = threading.Thread(target=server.handle_request, daemon=True)
        server_thread.start()

        assigned_port = server.server_address[1]
        response = urllib.request.urlopen(
            f"http://127.0.0.1:{assigned_port}/users/1"
        )
        assert response.read() == b"total=2 current=alice"

        server_thread.join(timeout=2)
        server.server_close()
        composed_app.connection.close()

    def test_oyaml_app_request_scope_created_fresh_per_request(self) -> None:
        """Each call to request_scope(...) produces an independent scope instance."""
        root = evaluate(app_oyaml, modules_public=True)
        composed_app = root.App.app  # type: ignore[union-attr]

        class FakeRequest:
            path = "/users/1"

        scope_a = composed_app.RequestScope(request=FakeRequest())
        scope_b = composed_app.RequestScope(request=FakeRequest())

        assert scope_a.current_user.user_id == 1
        assert scope_a.current_user.name == "alice"
        assert scope_b.current_user.user_id == 1
        assert scope_a is not scope_b

        composed_app.connection.close()
