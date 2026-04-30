"""Tests for ods_diff_hierarchy.collect: static helpers and persistence."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from odsbox_diff.ods_diff_hierarchy.collect import (
    Collector,
    load_collect_results,
    save_collect_results,
)


class TestJoinPath:
    def test_both_none(self) -> None:
        assert Collector._join_path(None, None) is None

    def test_left_none(self) -> None:
        assert Collector._join_path(None, "b") == "b"

    def test_right_none(self) -> None:
        assert Collector._join_path("a", None) == "a"

    def test_both(self) -> None:
        assert Collector._join_path("a", "b") == "a.b"


class TestHashPandasRow:
    def test_deterministic(self) -> None:
        row = pd.Series([1, "x", 3.5])
        h1 = Collector._hash_pandas_row(row)
        h2 = Collector._hash_pandas_row(row)
        assert h1 == h2
        assert len(h1) == 64  # sha256 hex

    def test_different_rows_differ(self) -> None:
        h1 = Collector._hash_pandas_row(pd.Series([1, 2, 3]))
        h2 = Collector._hash_pandas_row(pd.Series([1, 2, 4]))
        assert h1 != h2


class TestSaveLoadCollectResults:
    def test_json_roundtrip(self, tmp_path: Path) -> None:
        data = {"E": {"E.Name": "x", "E.Id": 1}}
        p = tmp_path / "result.json"
        save_collect_results(str(p), data)
        loaded = load_collect_results(str(p))
        assert loaded == data

    def test_zip_roundtrip(self, tmp_path: Path) -> None:
        data = {"E": {"E.Name": "x", "E.Id": 1}}
        p = tmp_path / "result.zip"
        save_collect_results(str(p), data)
        loaded = load_collect_results(str(p))
        assert loaded == data

    def test_zip_with_string_info(self, tmp_path: Path) -> None:
        data = {"k": "v"}
        p = tmp_path / "result.zip"
        save_collect_results(str(p), data, additional_info_for_zip="hello world")
        with zipfile.ZipFile(p, "r") as zf:
            assert zf.read("info.txt").decode("utf-8") == "hello world"
            assert json.loads(zf.read("result.json").decode("utf-8")) == data

    def test_zip_with_dict_info(self, tmp_path: Path) -> None:
        data = {"k": "v"}
        p = tmp_path / "result.zip"
        save_collect_results(str(p), data, additional_info_for_zip={"meta": 1})
        with zipfile.ZipFile(p, "r") as zf:
            assert json.loads(zf.read("info.txt").decode("utf-8")) == {"meta": 1}

    def test_zip_with_additional_files(self, tmp_path: Path) -> None:
        data = {"k": "v"}
        extra = tmp_path / "extra.txt"
        extra.write_text("extra-content", encoding="utf-8")
        p = tmp_path / "result.zip"
        save_collect_results(str(p), data, additional_files_for_zip=[str(extra)])
        with zipfile.ZipFile(p, "r") as zf:
            assert "extra.txt" in zf.namelist()
            assert zf.read("extra.txt").decode("utf-8") == "extra-content"

    def test_zip_skips_missing_additional_file(self, tmp_path: Path) -> None:
        p = tmp_path / "result.zip"
        save_collect_results(str(p), {"k": "v"}, additional_files_for_zip=[str(tmp_path / "missing.txt")])
        with zipfile.ZipFile(p, "r") as zf:
            assert "missing.txt" not in zf.namelist()

    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        p = tmp_path / "deep" / "nested" / "result.json"
        save_collect_results(str(p), {"k": "v"})
        assert p.exists()

    def test_save_bare_filename_no_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Regression: a bare filename (no directory component) should not blow up.
        monkeypatch.chdir(tmp_path)
        save_collect_results("result.json", {"k": "v"})
        assert (tmp_path / "result.json").exists()
