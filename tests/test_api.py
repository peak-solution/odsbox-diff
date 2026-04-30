"""Tests for the high-level programmatic API (odsbox_diff.api)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from odsbox_diff.api import (
    _resolve_config,
    collect_to_file,
    diff_file_to_file,
    diff_file_to_server,
    diff_server_to_server,
)
from odsbox_diff.connection.config import AppConfig, ServerConfig


@pytest.fixture
def app_config(basic_server_cfg: ServerConfig) -> AppConfig:
    return AppConfig(servers={"default": basic_server_cfg})


class TestResolveConfig:
    def test_from_appconfig(self, app_config: AppConfig) -> None:
        assert _resolve_config(app_config) is app_config

    def test_from_path(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "cfg.toml"
        cfg_file.write_text(
            '[server]\nurl = "http://localhost/api"\nmethod = "basic"\nusername = "u"\npassword = "p"\n',
            encoding="utf-8",
        )
        result = _resolve_config(str(cfg_file))
        assert isinstance(result, AppConfig)
        assert "default" in result.servers

    def test_from_pathlib_path(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "cfg.toml"
        cfg_file.write_text(
            '[server]\nurl = "http://localhost/api"\nmethod = "basic"\nusername = "u"\npassword = "p"\n',
            encoding="utf-8",
        )
        result = _resolve_config(cfg_file)
        assert isinstance(result, AppConfig)


class TestDiffFileToFile:
    def test_no_diff(self, tmp_path: Path) -> None:
        d = {"E": {"E.Name": "x"}}
        f1 = tmp_path / "a.json"
        f2 = tmp_path / "b.json"
        f1.write_text(json.dumps(d), encoding="utf-8")
        f2.write_text(json.dumps(d), encoding="utf-8")

        result = diff_file_to_file(f1, f2)
        assert not result

    def test_with_diff(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.json"
        f2 = tmp_path / "b.json"
        f1.write_text(json.dumps({"E": {"E.Name": "x"}}), encoding="utf-8")
        f2.write_text(json.dumps({"E": {"E.Name": "y"}}), encoding="utf-8")

        result = diff_file_to_file(f1, f2)
        assert result

    def test_str_paths(self, tmp_path: Path) -> None:
        d = {"E": {"E.Name": "x"}}
        f1 = tmp_path / "a.json"
        f1.write_text(json.dumps(d), encoding="utf-8")

        result = diff_file_to_file(str(f1), str(f1))
        assert not result


class TestDiffServerToServer:
    def test_returns_deepdiff(self, app_config: AppConfig) -> None:
        d = {"E": {"E.Name": "x"}}
        mock_con_i = MagicMock()

        with (
            patch("odsbox_diff.api.create_connection") as mock_create,
            patch("odsbox_diff.api.collect", return_value=(d, {})),
        ):
            mock_create.return_value.__enter__ = MagicMock(return_value=mock_con_i)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            result = diff_server_to_server(app_config, "TestStep", 1, 2)

        from deepdiff import DeepDiff

        assert isinstance(result, DeepDiff)
        assert not result  # same dict both sides


class TestDiffFileToServer:
    def test_baseline_matches_server(self, tmp_path: Path, app_config: AppConfig) -> None:
        d = {"E": {"E.Name": "x"}}
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps(d), encoding="utf-8")
        mock_con_i = MagicMock()

        with (
            patch("odsbox_diff.api.create_connection") as mock_create,
            patch("odsbox_diff.api.collect", return_value=(d, {})),
        ):
            mock_create.return_value.__enter__ = MagicMock(return_value=mock_con_i)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            result = diff_file_to_server(app_config, "TestStep", 42, baseline)

        assert not result

    def test_baseline_differs_from_server(self, tmp_path: Path, app_config: AppConfig) -> None:
        baseline_data = {"E": {"E.Name": "old"}}
        server_data = {"E": {"E.Name": "new"}}
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps(baseline_data), encoding="utf-8")
        mock_con_i = MagicMock()

        with (
            patch("odsbox_diff.api.create_connection") as mock_create,
            patch("odsbox_diff.api.collect", return_value=(server_data, {})),
        ):
            mock_create.return_value.__enter__ = MagicMock(return_value=mock_con_i)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            result = diff_file_to_server(app_config, "TestStep", 42, baseline)

        assert result


class TestCollectToFile:
    def test_no_validate(self, tmp_path: Path, app_config: AppConfig) -> None:
        d = {"E": {"E.Name": "x"}}
        output = tmp_path / "out.json"
        mock_con_i = MagicMock()

        with (
            patch("odsbox_diff.api.create_connection") as mock_create,
            patch("odsbox_diff.api.collect", return_value=(d, {})),
        ):
            mock_create.return_value.__enter__ = MagicMock(return_value=mock_con_i)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            result = collect_to_file(app_config, "TestStep", 1, output)

        assert result is None
        assert output.is_file()

    def test_validate_clean(self, tmp_path: Path, app_config: AppConfig) -> None:
        d = {"E": {"E.Name": "x"}}
        output = tmp_path / "out.json"
        mock_con_i = MagicMock()

        with (
            patch("odsbox_diff.api.create_connection") as mock_create,
            patch("odsbox_diff.api.collect", return_value=(d, {})),
        ):
            mock_create.return_value.__enter__ = MagicMock(return_value=mock_con_i)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            result = collect_to_file(app_config, "TestStep", 1, output, validate=True)

        assert result is not None
        assert not result  # no diff after round-trip

    def test_validate_dirty(self, tmp_path: Path, app_config: AppConfig) -> None:
        d = {"E": {"E.Name": "x"}}
        d_modified = {"E": {"E.Name": "y"}}
        output = tmp_path / "out.json"
        mock_con_i = MagicMock()

        with (
            patch("odsbox_diff.api.create_connection") as mock_create,
            patch("odsbox_diff.api.collect", return_value=(d, {})),
            patch("odsbox_diff.api.save_collect_results"),
            patch("odsbox_diff.api.load_collect_results", return_value=d_modified),
        ):
            mock_create.return_value.__enter__ = MagicMock(return_value=mock_con_i)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            result = collect_to_file(app_config, "TestStep", 1, output, validate=True)

        assert result  # truthy = diff found
