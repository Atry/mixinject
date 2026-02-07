from pathlib import PurePath

import pytest

from mixinject import AbsoluteReference, RelativeReference, resource_reference_from_pure_path


class TestResourceReferenceFromPurePath:
    """Test resource_reference_from_pure_path function."""

    def test_relative_path_single_level_up(self) -> None:
        result = resource_reference_from_pure_path(PurePath("../foo/bar"))
        assert result == RelativeReference(de_bruijn_index=1, path=("foo", "bar"))

    def test_relative_path_multiple_levels_up(self) -> None:
        result = resource_reference_from_pure_path(PurePath("../../config"))
        assert result == RelativeReference(de_bruijn_index=2, path=("config",))

    def test_relative_path_three_levels_up(self) -> None:
        result = resource_reference_from_pure_path(PurePath("../../../a/b/c"))
        assert result == RelativeReference(de_bruijn_index=3, path=("a", "b", "c"))

    def test_relative_path_no_levels_up(self) -> None:
        result = resource_reference_from_pure_path(PurePath("foo/bar"))
        assert result == RelativeReference(de_bruijn_index=0, path=("foo", "bar"))

    def test_relative_path_single_part(self) -> None:
        result = resource_reference_from_pure_path(PurePath("foo"))
        assert result == RelativeReference(de_bruijn_index=0, path=("foo",))

    def test_relative_path_pardir_only(self) -> None:
        result = resource_reference_from_pure_path(PurePath(".."))
        assert result == RelativeReference(de_bruijn_index=1, path=())

    def test_relative_path_multiple_pardir_only(self) -> None:
        result = resource_reference_from_pure_path(PurePath("../.."))
        assert result == RelativeReference(de_bruijn_index=2, path=())

    def test_curdir_returns_empty_parts(self) -> None:
        result = resource_reference_from_pure_path(PurePath("."))
        assert result == RelativeReference(de_bruijn_index=0, path=())

    def test_absolute_path_unix_style(self) -> None:
        result = resource_reference_from_pure_path(PurePath("/absolute/path"))
        assert result == AbsoluteReference(path=("absolute", "path"))

    def test_absolute_path_single_part(self) -> None:
        result = resource_reference_from_pure_path(PurePath("/root"))
        assert result == AbsoluteReference(path=("root",))

    def test_absolute_path_deep_nested(self) -> None:
        result = resource_reference_from_pure_path(PurePath("/a/b/c/d/e"))
        assert result == AbsoluteReference(path=("a", "b", "c", "d", "e"))

    def test_non_normalized_pardir_in_middle_raises_valueerror(self) -> None:
        with pytest.raises(ValueError, match="Path is not normalized"):
            resource_reference_from_pure_path(PurePath("foo/../bar"))

    def test_non_normalized_pardir_at_end_raises_valueerror(self) -> None:
        with pytest.raises(ValueError, match="Path is not normalized"):
            resource_reference_from_pure_path(PurePath("foo/bar/.."))

    def test_non_normalized_absolute_path_raises_valueerror(self) -> None:
        with pytest.raises(ValueError, match="Path is not normalized"):
            resource_reference_from_pure_path(PurePath("/absolute/../path"))

    def test_absolute_path_with_curdir_is_normalized_by_purepath(self) -> None:
        result = resource_reference_from_pure_path(PurePath("/absolute/./path"))
        assert result == AbsoluteReference(path=("absolute", "path"))

    def test_return_type_is_relative_or_absolute_reference(self) -> None:
        result = resource_reference_from_pure_path(PurePath("foo"))
        assert isinstance(result, (RelativeReference, AbsoluteReference))

    def test_relative_reference_type(self) -> None:
        result = resource_reference_from_pure_path(PurePath("../foo"))
        assert isinstance(result, RelativeReference)

    def test_absolute_reference_type(self) -> None:
        result = resource_reference_from_pure_path(PurePath("/foo"))
        assert isinstance(result, AbsoluteReference)

    def test_empty_relative_path(self) -> None:
        result = resource_reference_from_pure_path(PurePath(""))
        assert result == RelativeReference(de_bruijn_index=0, path=())

    def test_relative_path_with_pardir_then_parts(self) -> None:
        result = resource_reference_from_pure_path(PurePath("../../foo/bar/baz"))
        assert result == RelativeReference(de_bruijn_index=2, path=("foo", "bar", "baz"))
