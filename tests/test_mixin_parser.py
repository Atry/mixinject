"""Tests for Overlay file parsing and evaluation."""

from pathlib import Path

import pytest

from overlay.language import LexicalReference, QualifiedThisReference
from overlay.language.mixin_directory import (
    DirectoryMixinDefinition,
    evaluate_mixin_directory,
)
from overlay.language.mixin_parser import (
    FileMixinDefinition,
    parse_mixin_file,
    parse_mixin_value,
    parse_reference,
)


class TestParseReference:
    """Tests for parse_reference function."""

    def test_simple_reference(self) -> None:
        """[ParentMixin] should produce LexicalReference."""
        result = parse_reference(["ParentMixin"])
        assert isinstance(result, LexicalReference)
        assert result.path == ("ParentMixin",)

    def test_path_reference(self) -> None:
        """[path, to, mixin] should produce LexicalReference."""
        result = parse_reference(["path", "to", "mixin"])
        assert isinstance(result, LexicalReference)
        assert result.path == ("path", "to", "mixin")

    def test_qualified_this_reference(self) -> None:
        """[SelfName, ~, property] should produce QualifiedThisReference."""
        result = parse_reference(["SelfName", None, "property"])
        assert isinstance(result, QualifiedThisReference)
        assert result.self_name == "SelfName"
        assert result.path == ("property",)

    def test_qualified_this_with_path(self) -> None:
        """[SelfName, ~, property, path] should produce QualifiedThisReference."""
        result = parse_reference(["SelfName", None, "property", "path"])
        assert isinstance(result, QualifiedThisReference)
        assert result.self_name == "SelfName"
        assert result.path == ("property", "path")

    def test_empty_array_raises(self) -> None:
        """Empty array should raise ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            parse_reference([])

    def test_non_string_element_raises(self) -> None:
        """Non-string element in regular reference should raise ValueError."""
        with pytest.raises(ValueError, match="must be a string"):
            parse_reference(["path", 123, "mixin"])


class TestParseMixinValue:
    """Tests for parse_mixin_value function."""

    def test_object_value(self) -> None:
        """Object value should be parsed as properties only."""
        value = {"name": "test", "value": 42}
        result = parse_mixin_value(value, source_file=Path("test.oyaml"))

        assert result.inheritances == ()
        assert result.property_definitions == ({"name": "test", "value": 42},)
        assert result.scalar_values == ()

    def test_scalar_value(self) -> None:
        """Scalar value should be parsed as scalar_values."""
        result = parse_mixin_value(42, source_file=Path("test.oyaml"))

        assert result.inheritances == ()
        assert result.property_definitions == ()
        assert result.scalar_values == (42,)

    def test_array_with_inheritance(self) -> None:
        """Array with inheritance reference should be parsed."""
        value = [["ParentMixin"], {"property": "value"}]
        result = parse_mixin_value(value, source_file=Path("test.oyaml"))

        assert len(result.inheritances) == 1
        assert isinstance(result.inheritances[0], LexicalReference)
        assert result.property_definitions == ({"property": "value"},)
        assert result.scalar_values == ()

    def test_array_with_scalar(self) -> None:
        """Array with scalar value should be parsed."""
        value = [42, ["ParentMixin"]]
        result = parse_mixin_value(value, source_file=Path("test.oyaml"))

        assert len(result.inheritances) == 1
        assert result.scalar_values == (42,)


class TestParseMixinFile:
    """Tests for parse_mixin_file function."""

    def test_parse_yaml_file(self, tmp_path: Path) -> None:
        """Parse a YAML mixin file."""
        yaml_content = """
bar:
  baz: "qux"
  sub:
    - [bar, ~, a]
    - c: [sub, ~, b]

test_late_binding:
  my_mixin1:
    inner:
      field1: "value1"
    early_binding:
      - [test_late_binding, ~, my_mixin1, inner]
    late_binding:
      - [my_mixin1, ~, inner]
"""
        yaml_file = tmp_path / "foo.oyaml"
        yaml_file.write_text(yaml_content)

        result = parse_mixin_file(yaml_file)

        assert "bar" in result
        assert "test_late_binding" in result

        bar_defs = result["bar"]
        assert len(bar_defs) == 1
        assert isinstance(bar_defs[0], FileMixinDefinition)
        assert "baz" in bar_defs[0].underlying
        assert "sub" in bar_defs[0].underlying

    def test_parse_json_file(self, tmp_path: Path) -> None:
        """Parse a JSON mixin file."""
        json_content = '{"TestMixin": {"value": 42}}'
        json_file = tmp_path / "test.ojson"
        json_file.write_text(json_content)

        result = parse_mixin_file(json_file)

        assert "TestMixin" in result
        assert len(result["TestMixin"]) == 1
        assert isinstance(result["TestMixin"][0], FileMixinDefinition)

    def test_parse_toml_file(self, tmp_path: Path) -> None:
        """Parse a TOML mixin file."""
        toml_content = """
[TestMixin]
value = 42
name = "test"
"""
        toml_file = tmp_path / "test.otoml"
        toml_file.write_text(toml_content)

        result = parse_mixin_file(toml_file)

        assert "TestMixin" in result
        assert len(result["TestMixin"]) == 1
        assert isinstance(result["TestMixin"][0], FileMixinDefinition)

    def test_invalid_format_raises(self, tmp_path: Path) -> None:
        """Unrecognized file format should raise ValueError."""
        invalid_file = tmp_path / "test.txt"
        invalid_file.write_text("{}")
        with pytest.raises(ValueError, match="Unrecognized Overlay file format"):
            parse_mixin_file(invalid_file)

    def test_multiple_origins(self, tmp_path: Path) -> None:
        """Mixin with multiple property definitions should have multiple origins."""
        yaml_content = """
MultiOriginMixin:
  - [BaseMixin]
  - field1: "value1"
  - field2: "value2"
"""
        yaml_file = tmp_path / "multi.oyaml"
        yaml_file.write_text(yaml_content)

        result = parse_mixin_file(yaml_file)

        assert "MultiOriginMixin" in result
        origins = result["MultiOriginMixin"]
        assert len(origins) == 2  # Two property definitions = two origins

        # First origin has inheritance and first properties
        assert len(origins[0].inherits) == 1
        assert "field1" in origins[0].underlying

        # Second origin has no inheritance, just properties
        assert len(origins[1].inherits) == 0
        assert "field2" in origins[1].underlying


class TestFileMixinDefinition:
    """Tests for FileMixinDefinition class."""

    def test_iter_yields_property_names(self) -> None:
        """__iter__ should yield property names."""
        definition = FileMixinDefinition(
            inherits=(),
            is_public=True,
            underlying={"prop1": "value1", "prop2": "value2"},
            scalar_values=(),
            source_file=Path("test.oyaml"),
        )

        keys = list(definition)
        assert "prop1" in keys
        assert "prop2" in keys

    def test_getitem_returns_child_definition(self) -> None:
        """__getitem__ should return child FileMixinDefinition."""
        definition = FileMixinDefinition(
            inherits=(),
            is_public=True,
            underlying={"child": {"nested": "value"}},
            scalar_values=(),
            source_file=Path("test.oyaml"),
        )

        children = definition["child"]
        assert len(children) == 1
        child = children[0]
        assert isinstance(child, FileMixinDefinition)
        assert "nested" in child.underlying


class TestDirectoryMixinDefinition:
    """Tests for DirectoryMixinDefinition class."""

    def test_discovers_mixin_files(self, tmp_path: Path) -> None:
        """Should discover *.oyaml files in directory."""
        mixin_file = tmp_path / "test.oyaml"
        mixin_file.write_text("TestMixin:\n  value: 42\n")

        definition = DirectoryMixinDefinition(
            inherits=(),
            is_public=True,
            underlying=tmp_path,
        )

        keys = list(definition)
        assert "test" in keys

    def test_discovers_subdirectories(self, tmp_path: Path) -> None:
        """Should discover subdirectories."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        definition = DirectoryMixinDefinition(
            inherits=(),
            is_public=True,
            underlying=tmp_path,
        )

        keys = list(definition)
        assert "subdir" in keys

    def test_discovers_multiple_formats(self, tmp_path: Path) -> None:
        """Should discover yaml, json, and toml files."""
        (tmp_path / "yaml_test.oyaml").write_text("A: {}")
        (tmp_path / "json_test.ojson").write_text('{"B": {}}')
        (tmp_path / "toml_test.otoml").write_text("[C]\n")

        definition = DirectoryMixinDefinition(
            inherits=(),
            is_public=True,
            underlying=tmp_path,
        )

        keys = list(definition)
        assert "yaml_test" in keys
        assert "json_test" in keys
        assert "toml_test" in keys


class TestEvaluateMixinDirectory:
    """Tests for evaluate_mixin_directory function."""

    def test_evaluate_simple_directory(self, tmp_path: Path) -> None:
        """Evaluate a simple directory with one mixin file."""
        yaml_content = """
TestMixin:
  value: 42
  name: "test"
"""
        (tmp_path / "test.oyaml").write_text(yaml_content)

        scope = evaluate_mixin_directory(tmp_path)

        assert hasattr(scope, "test")
        test_scope = scope.test
        assert hasattr(test_scope, "TestMixin")

    def test_evaluate_nested_directory(self, tmp_path: Path) -> None:
        """Evaluate a directory with subdirectories."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.oyaml").write_text("NestedMixin:\n  value: 1\n")

        scope = evaluate_mixin_directory(tmp_path)

        assert hasattr(scope, "subdir")
        subdir_scope = scope.subdir
        assert hasattr(subdir_scope, "nested")

    def test_non_directory_raises(self, tmp_path: Path) -> None:
        """Non-directory path should raise ValueError."""
        non_dir = tmp_path / "not_a_directory.txt"
        non_dir.write_text("content")

        with pytest.raises(ValueError, match="not a directory"):
            evaluate_mixin_directory(non_dir)

    def test_evaluate_with_inheritance(self, tmp_path: Path) -> None:
        """Evaluate mixins with inheritance references."""
        yaml_content = """
Base:
  base_value: "from_base"

Derived:
  - [Base]
  - derived_value: "from_derived"
"""
        (tmp_path / "test.oyaml").write_text(yaml_content)

        scope = evaluate_mixin_directory(tmp_path)

        assert hasattr(scope, "test")
        test_scope = scope.test
        assert hasattr(test_scope, "Base")
        assert hasattr(test_scope, "Derived")
