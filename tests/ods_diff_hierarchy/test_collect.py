"""Tests for ods_diff_hierarchy.collect: static helpers and persistence."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pandas as pd
import pytest
from requests import HTTPError

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

    def test_bulk_hash_ignores_id_when_excluded(self) -> None:
        row_a = pd.Series([101, "gp", "vals", "flags"], index=["id", "generation_parameters", "values", "flags"])
        row_b = pd.Series([202, "gp", "vals", "flags"], index=["id", "generation_parameters", "values", "flags"])

        h1 = Collector._hash_pandas_row(row_a.drop(labels=["id"]))
        h2 = Collector._hash_pandas_row(row_b.drop(labels=["id"]))
        assert h1 == h2


class TestCollectBulkData:
    def _mock_collector(self) -> tuple[Collector, Any, Any]:
        """Create a Collector with mocked ConI and ModelCache."""
        mock_con_i: Any = MagicMock()
        mock_mc: Any = MagicMock()
        mock_con_i.mc = mock_mc
        collector = Collector(cast(Any, mock_con_i))
        return collector, mock_con_i, mock_mc

    def test_collect_bulk_data_success(self) -> None:
        """Test successful bulk hash computation for LocalColumns."""
        collector, mock_con_i, mock_mc = self._mock_collector()

        sub_matrix_entity = MagicMock()
        sub_matrix_entity.name = "SubMatrix"
        local_column_entity = MagicMock()
        local_column_entity.name = "LocalColumn"
        mock_mc.entity_by_base_name.side_effect = lambda name: (
            sub_matrix_entity if name == "AoSubMatrix" else local_column_entity
        )

        attr_id = MagicMock()
        attr_id.name = "Id"
        attr_values = MagicMock()
        attr_values.name = "Values"
        attr_gp = MagicMock()
        attr_gp.name = "GenerationParameters"
        attr_flags = MagicMock()
        attr_flags.name = "Flags"
        mock_mc.attribute_no_throw.side_effect = lambda entity, name: {
            "id": attr_id,
            "values": attr_values,
            "generation_parameters": attr_gp,
            "flags": attr_flags,
        }.get(name)

        submatrices_df = pd.DataFrame(
            {
                "id": [1],
                "measurement": [10],
                "number_of_rows": [2],
            }
        )
        bulk_data_df = pd.DataFrame(
            {
                "LocalColumn.Id": [101, 102],
                "GenerationParameters": ["gp1", "gp2"],
                "Values": [[1, 2, 3], [4, 5, 6]],
                "Flags": [[0, 0, 0], [0, 1, 0]],
            }
        )
        mock_con_i.query_data.side_effect = [submatrices_df, bulk_data_df]
        lookup: dict[tuple[str, int], dict[str, Any]] = {
            ("LocalColumn", 101): {},
            ("LocalColumn", 102): {},
        }

        collector._collect_bulk_data(lookup, "measurement", 10, show_progress=False)

        assert "_BULK_HASH" in lookup[("LocalColumn", 101)]
        assert "_BULK_HASH" in lookup[("LocalColumn", 102)]
        assert lookup[("LocalColumn", 101)]["_BULK_HASH"] != lookup[("LocalColumn", 102)]["_BULK_HASH"]

    def test_collect_bulk_data_missing_required_attributes(self) -> None:
        """Test that bulk hash is skipped when required attributes are missing."""
        collector, mock_con_i, mock_mc = self._mock_collector()

        sub_matrix_entity = MagicMock()
        sub_matrix_entity.name = "SubMatrix"
        local_column_entity = MagicMock()
        local_column_entity.name = "LocalColumn"
        mock_mc.entity_by_base_name.side_effect = lambda name: (
            sub_matrix_entity if name == "AoSubMatrix" else local_column_entity
        )

        mock_mc.attribute_no_throw.return_value = None

        submatrices_df = pd.DataFrame(
            {
                "id": [1],
                "measurement": [10],
                "number_of_rows": [1],
            }
        )
        mock_con_i.query_data.return_value = submatrices_df
        lookup: dict[tuple[str, int], dict[str, Any]] = {}
        collector._collect_bulk_data(lookup, "measurement", 10, show_progress=False)
        assert mock_con_i.query_data.call_count == 1

    def test_collect_bulk_data_http_error_handling(self) -> None:
        """Test that HTTPError is caught and logged without crashing."""
        collector, mock_con_i, mock_mc = self._mock_collector()

        sub_matrix_entity = MagicMock()
        sub_matrix_entity.name = "SubMatrix"
        local_column_entity = MagicMock()
        local_column_entity.name = "LocalColumn"
        mock_mc.entity_by_base_name.side_effect = lambda name: (
            sub_matrix_entity if name == "AoSubMatrix" else local_column_entity
        )

        attr_id = MagicMock()
        attr_id.name = "Id"
        attr_values = MagicMock()
        attr_values.name = "Values"
        attr_gp = MagicMock()
        attr_gp.name = "GenerationParameters"
        attr_flags = MagicMock()
        attr_flags.name = "Flags"
        mock_mc.attribute_no_throw.side_effect = lambda entity, name: {
            "id": attr_id,
            "values": attr_values,
            "generation_parameters": attr_gp,
            "flags": attr_flags,
        }.get(name)

        submatrices_df = pd.DataFrame(
            {
                "id": [1],
                "measurement": [10],
                "number_of_rows": [1],
            }
        )
        mock_con_i.query_data.side_effect = [submatrices_df, HTTPError("Connection failed")]
        lookup: dict[tuple[str, int], dict[str, Any]] = {
            ("SubMatrix", 1): {},
        }
        collector._collect_bulk_data(lookup, "measurement", 10, show_progress=False)
        assert "_BULK_HASH_CALCULATION_ERROR" in lookup[("SubMatrix", 1)]
        assert "Unable to retrieve bulk for Submatrix 1" in lookup[("SubMatrix", 1)]["_BULK_HASH_CALCULATION_ERROR"]

    def test_collect_bulk_data_id_excluded_from_hash(self) -> None:
        """Verify that changing only the id column does not change the bulk hash."""
        collector, mock_con_i, mock_mc = self._mock_collector()

        sub_matrix_entity = MagicMock()
        sub_matrix_entity.name = "SubMatrix"
        local_column_entity = MagicMock()
        local_column_entity.name = "LocalColumn"
        mock_mc.entity_by_base_name.side_effect = lambda name: (
            sub_matrix_entity if name == "AoSubMatrix" else local_column_entity
        )

        attr_id = MagicMock()
        attr_id.name = "Id"
        attr_values = MagicMock()
        attr_values.name = "Values"
        attr_gp = MagicMock()
        attr_gp.name = "GenerationParameters"
        attr_flags = MagicMock()
        attr_flags.name = "Flags"
        mock_mc.attribute_no_throw.side_effect = lambda entity, name: {
            "id": attr_id,
            "values": attr_values,
            "generation_parameters": attr_gp,
            "flags": attr_flags,
        }.get(name)

        submatrices_df = pd.DataFrame(
            {
                "id": [1],
                "measurement": [10],
                "number_of_rows": [1],
            }
        )

        bulk_data_df = pd.DataFrame(
            {
                "LocalColumn.Id": [101, 202],
                "GenerationParameters": ["same_gp", "same_gp"],
                "Values": ["same_vals", "same_vals"],
                "Flags": ["same_flags", "same_flags"],
            }
        )

        mock_con_i.query_data.side_effect = [submatrices_df, bulk_data_df]

        lookup: dict[tuple[str, int], dict[str, Any]] = {
            ("LocalColumn", 101): {},
            ("LocalColumn", 202): {},
        }

        collector._collect_bulk_data(lookup, "measurement", 10, show_progress=False)

        hash1 = lookup[("LocalColumn", 101)]["_BULK_HASH"]
        hash2 = lookup[("LocalColumn", 202)]["_BULK_HASH"]
        assert hash1 == hash2


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
