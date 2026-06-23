"""Tests for ods_diff_hierarchy.diff."""

from __future__ import annotations

import json
from pathlib import Path

from odsbox_diff.ods_diff_hierarchy.diff import diff_dictionaries, dump_diff_as_json


class TestDiffDictionaries:
    def test_identical_dicts_no_diff(self) -> None:
        d1 = {"a": 1, "b": {"c": 2}}
        d2 = {"a": 1, "b": {"c": 2}}
        result = diff_dictionaries(d1, d2, [], [])
        assert not result

    def test_value_change_detected(self) -> None:
        d1 = {"a": 1}
        d2 = {"a": 2}
        result = diff_dictionaries(d1, d2, [], [])
        assert result
        assert "values_changed" in result

    def test_default_id_excluded(self) -> None:
        d1 = {"E": {"E.Id": 1, "E.Name": "x"}}
        d2 = {"E": {"E.Id": 999, "E.Name": "x"}}
        result = diff_dictionaries(d1, d2, [], [])
        assert not result

    def test_default_date_created_excluded(self) -> None:
        d1 = {"E": {"E.DateCreated": "2024-01-01", "E.Name": "x"}}
        d2 = {"E": {"E.DateCreated": "2025-01-01", "E.Name": "x"}}
        result = diff_dictionaries(d1, d2, [], [])
        assert not result

    def test_default_version_excluded(self) -> None:
        d1 = {"E": {"E.Version": 1, "E.Name": "x"}}
        d2 = {"E": {"E.Version": 2, "E.Name": "x"}}
        result = diff_dictionaries(d1, d2, [], [])
        assert not result

    def test_custom_exclude_regex(self) -> None:
        d1 = {"E": {"E.Foo": 1}}
        d2 = {"E": {"E.Foo": 2}}
        assert diff_dictionaries(d1, d2, [], [])
        assert not diff_dictionaries(d1, d2, [r"\.Foo'\]$"], [])

    def test_custom_exclude_path(self) -> None:
        d1 = {"a": 1}
        d2 = {"a": 2}
        assert diff_dictionaries(d1, d2, [], [])
        assert not diff_dictionaries(d1, d2, [], ["root['a']"])

    def test_bulk_hash_difference_detected(self) -> None:
        """Verify that _BULK_HASH differences are detected (not excluded by default patterns)."""
        d1 = {"E": {"E.Name": "test", "_BULK_HASH": "hash123"}}
        d2 = {"E": {"E.Name": "test", "_BULK_HASH": "hash456"}}
        result = diff_dictionaries(d1, d2, [], [])
        assert result
        assert "values_changed" in result
        # Verify the diff includes the _BULK_HASH change
        assert any("_BULK_HASH" in key for key in result["values_changed"].keys())

    def test_double_underscore_bulk_hash_ignored(self) -> None:
        """Verify that __BULK_HASH is ignored by DeepDiff (treated as private attribute)."""
        # This test demonstrates why __BULK_HASH doesn't work.
        # Double underscore attributes are treated as private and ignored by default.
        d1 = {"E": {"E.Name": "test", "__BULK_HASH": "hash123"}}
        d2 = {"E": {"E.Name": "test", "__BULK_HASH": "hash456"}}
        result = diff_dictionaries(d1, d2, [], [])
        # No diff should be detected because __BULK_HASH is ignored as a private variable
        assert not result


class TestDumpDiffAsJson:
    def test_writes_valid_json(self, tmp_path: Path) -> None:
        d1 = {"x": 1}
        d2 = {"x": 2}
        diff = diff_dictionaries(d1, d2, [], [])
        out = tmp_path / "diff.json"
        dump_diff_as_json(str(out), diff)
        # File exists and is valid JSON
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert "values_changed" in loaded
