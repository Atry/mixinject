from pathlib import PurePath

import pytest

from mixinject import AbsoluteReference, RelativeReference, ResourceReference


class TestResourceReferenceFromPurePath:
    """Test ResourceReference.from_pure_path static method."""

    def test_relative_path_single_level_up(self) -> None:
        result = ResourceReference.from_pure_path(PurePath("../foo/bar"))
        assert result == RelativeReference(levels_up=1, parts=("foo", "bar"))

    def test_relative_path_multiple_levels_up(self) -> None:
        result = ResourceReference.from_pure_path(PurePath("../../config"))
        assert result == RelativeReference(levels_up=2, parts=("config",))

    def test_relative_path_three_levels_up(self) -> None:
        result = ResourceReference.from_pure_path(PurePath("../../../a/b/c"))
        assert result == RelativeReference(levels_up=3, parts=("a", "b", "c"))

    def test_relative_path_no_levels_up(self) -> None:
        result = ResourceReference.from_pure_path(PurePath("foo/bar"))
        assert result == RelativeReference(levels_up=0, parts=("foo", "bar"))

    def test_relative_path_single_part(self) -> None:
        result = ResourceReference.from_pure_path(PurePath("foo"))
        assert result == RelativeReference(levels_up=0, parts=("foo",))

    def test_relative_path_pardir_only(self) -> None:
        result = ResourceReference.from_pure_path(PurePath(".."))
        assert result == RelativeReference(levels_up=1, parts=())

    def test_relative_path_multiple_pardir_only(self) -> None:
        result = ResourceReference.from_pure_path(PurePath("../.."))
        assert result == RelativeReference(levels_up=2, parts=())

    def test_curdir_returns_empty_parts(self) -> None:
        result = ResourceReference.from_pure_path(PurePath("."))
        assert result == RelativeReference(levels_up=0, parts=())

    def test_absolute_path_unix_style(self) -> None:
        result = ResourceReference.from_pure_path(PurePath("/absolute/path"))
        assert result == AbsoluteReference(parts=("absolute", "path"))

    def test_absolute_path_single_part(self) -> None:
        result = ResourceReference.from_pure_path(PurePath("/root"))
        assert result == AbsoluteReference(parts=("root",))

    def test_absolute_path_deep_nested(self) -> None:
        result = ResourceReference.from_pure_path(PurePath("/a/b/c/d/e"))
        assert result == AbsoluteReference(parts=("a", "b", "c", "d", "e"))

    def test_non_normalized_pardir_in_middle_raises_valueerror(self) -> None:
        with pytest.raises(ValueError, match="Path is not normalized"):
            ResourceReference.from_pure_path(PurePath("foo/../bar"))

    def test_non_normalized_pardir_at_end_raises_valueerror(self) -> None:
        with pytest.raises(ValueError, match="Path is not normalized"):
            ResourceReference.from_pure_path(PurePath("foo/bar/.."))

    def test_non_normalized_absolute_path_raises_valueerror(self) -> None:
        with pytest.raises(ValueError, match="Path is not normalized"):
            ResourceReference.from_pure_path(PurePath("/absolute/../path"))

    def test_absolute_path_with_curdir_is_normalized_by_purepath(self) -> None:
        result = ResourceReference.from_pure_path(PurePath("/absolute/./path"))
        assert result == AbsoluteReference(parts=("absolute", "path"))

    def test_return_type_is_resource_reference(self) -> None:
        result = ResourceReference.from_pure_path(PurePath("foo"))
        assert isinstance(result, ResourceReference)

    def test_relative_reference_is_resource_reference_subclass(self) -> None:
        result = ResourceReference.from_pure_path(PurePath("../foo"))
        assert isinstance(result, ResourceReference)
        assert isinstance(result, RelativeReference)

    def test_absolute_reference_is_resource_reference_subclass(self) -> None:
        result = ResourceReference.from_pure_path(PurePath("/foo"))
        assert isinstance(result, ResourceReference)
        assert isinstance(result, AbsoluteReference)

    def test_empty_relative_path(self) -> None:
        result = ResourceReference.from_pure_path(PurePath(""))
        assert result == RelativeReference(levels_up=0, parts=())

    def test_relative_path_with_pardir_then_parts(self) -> None:
        result = ResourceReference.from_pure_path(PurePath("../../foo/bar/baz"))
        assert result == RelativeReference(levels_up=2, parts=("foo", "bar", "baz"))
