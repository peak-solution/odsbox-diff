"""Tests for diff._parse_server_id, diff._parse_id_or_file, diff_ods_tests, and collect_ods_test."""

from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from odsbox_diff.connection.config import AuthMethod, ServerConfig
from odsbox_diff.diff import (
    _cli_create_config,
    _parse_id_or_file,
    _parse_server_id,
    cli,
    collect_ods_test,
    create_config_file,
    diff_ods_tests,
)


@pytest.fixture
def single_server_dict(basic_server_cfg: ServerConfig) -> dict[str, ServerConfig]:
    return {"default": basic_server_cfg}


@pytest.fixture
def multi_server_dict() -> dict[str, ServerConfig]:
    return {
        "prod": ServerConfig(url="http://prod", auth_method=AuthMethod.BASIC, username="u", password="p"),
        "staging": ServerConfig(url="http://staging", auth_method=AuthMethod.BASIC, username="u", password="p"),
    }


class TestParseServerId:
    def test_plain_id_single_server(self, single_server_dict: dict[str, ServerConfig]) -> None:
        cfg, iid = _parse_server_id("42", single_server_dict, queries=None, multi_server=False)
        assert cfg is single_server_dict["default"]
        assert iid == 42

    def test_server_colon_id(self, multi_server_dict: dict[str, ServerConfig]) -> None:
        cfg, iid = _parse_server_id("prod:7", multi_server_dict, queries=None, multi_server=True)
        assert cfg is multi_server_dict["prod"]
        assert iid == 7

    def test_unknown_server(self, multi_server_dict: dict[str, ServerConfig]) -> None:
        with pytest.raises(ValueError, match="not found"):
            _parse_server_id("ghost:1", multi_server_dict, queries=None, multi_server=True)

    def test_non_integer_after_colon(self, multi_server_dict: dict[str, ServerConfig]) -> None:
        with pytest.raises(ValueError, match="must be an integer, JSON condition, or named query"):
            _parse_server_id("prod:abc", multi_server_dict, queries=None, multi_server=True)

    def test_plain_id_with_multi_server(self, multi_server_dict: dict[str, ServerConfig]) -> None:
        with pytest.raises(ValueError, match="Multiple servers"):
            _parse_server_id("5", multi_server_dict, queries=None, multi_server=True)

    def test_non_integer_plain(self, single_server_dict: dict[str, ServerConfig]) -> None:
        with pytest.raises(ValueError, match="must be an integer"):
            _parse_server_id("abc", single_server_dict, queries=None, multi_server=False)

    def test_colon_format_with_single_server_works(self, single_server_dict: dict[str, ServerConfig]) -> None:
        cfg, iid = _parse_server_id("default:9", single_server_dict, queries=None, multi_server=False)
        assert cfg is single_server_dict["default"]
        assert iid == 9

    def test_json_dict_plain(self, single_server_dict: dict[str, ServerConfig]) -> None:
        condition = '{"Name": "my_step"}'
        cfg, iid = _parse_server_id(condition, single_server_dict, queries=None, multi_server=False)
        assert cfg is single_server_dict["default"]
        assert iid == {"Name": "my_step"}

    def test_json_dict_after_colon(self, multi_server_dict: dict[str, ServerConfig]) -> None:
        import json

        condition = {"gte": 5}
        cfg, iid = _parse_server_id(f"prod:{json.dumps(condition)}", multi_server_dict, queries=None, multi_server=True)
        assert cfg is multi_server_dict["prod"]
        assert iid == condition

    def test_json_dict_plain_multi_server_raises(self, multi_server_dict: dict[str, ServerConfig]) -> None:
        with pytest.raises(ValueError, match="Multiple servers"):
            _parse_server_id('{"Name": "x"}', multi_server_dict, queries=None, multi_server=True)

    def test_named_query_single_server(self, single_server_dict: dict[str, ServerConfig]) -> None:
        queries = [{"name": "first", "condition": {"Name": "My Step"}}]
        cfg, iid = _parse_server_id("first", single_server_dict, queries=queries, multi_server=False)
        assert cfg is single_server_dict["default"]
        assert iid == {"Name": "My Step"}

    def test_named_query_after_colon(self, multi_server_dict: dict[str, ServerConfig]) -> None:
        queries = [{"name": "baseline", "condition": {"Name": "Step A"}}]
        cfg, iid = _parse_server_id("prod:baseline", multi_server_dict, queries=queries, multi_server=True)
        assert cfg is multi_server_dict["prod"]
        assert iid == {"Name": "Step A"}


class TestParseIdOrFile:
    def test_file_prefix_returns_path(self) -> None:
        cfg, iid, fpath = _parse_id_or_file("file:./foo.json", {}, queries=None, multi_server=False)
        assert cfg is None
        assert iid is None
        assert fpath == "./foo.json"

    def test_file_prefix_absolute_path(self) -> None:
        cfg, iid, fpath = _parse_id_or_file("file:C:/data/result.json", {}, queries=None, multi_server=False)
        assert fpath == "C:/data/result.json"

    def test_server_ref_unchanged(self, single_server_dict: dict[str, ServerConfig]) -> None:
        cfg, iid, fpath = _parse_id_or_file("42", single_server_dict, queries=None, multi_server=False)
        assert cfg is single_server_dict["default"]
        assert iid == 42
        assert fpath is None

    def test_server_colon_ref(self, multi_server_dict: dict[str, ServerConfig]) -> None:
        cfg, iid, fpath = _parse_id_or_file("prod:7", multi_server_dict, queries=None, multi_server=True)
        assert cfg is multi_server_dict["prod"]
        assert iid == 7
        assert fpath is None


class TestDiffOdsTestsFileSources:
    def test_file_to_file_no_server_connection(self, tmp_path: Path) -> None:
        """Both sides from files — no server connection should be opened."""
        import json

        d1 = {"E": {"E.Name": "x", "E.Value": 1}}
        d2 = {"E": {"E.Name": "x", "E.Value": 2}}
        f1 = tmp_path / "inst1.json"
        f2 = tmp_path / "inst2.json"
        f1.write_text(json.dumps(d1), encoding="utf-8")
        f2.write_text(json.dumps(d2), encoding="utf-8")
        result_file = str(tmp_path / "result.json")

        with patch("odsbox_diff.diff.create_connection") as mock_conn:
            rc = diff_ods_tests(
                server1_cfg=None,
                server2_cfg=None,
                entity_name="TestStep",
                inst1_condition=None,
                inst2_condition=None,
                result_file=result_file,
                dump_dictionaries=False,
                exclude_regex_paths=[],
                exclude_paths=[],
                no_bulk=True,
                bulk_progress_bar=False,
                file1_path=str(f1),
                file2_path=str(f2),
            )
            mock_conn.assert_not_called()

        assert rc == 100  # different values -> diff found
        assert Path(result_file).is_file()

    def test_file_to_file_no_diff(self, tmp_path: Path) -> None:
        import json

        d = {"E": {"E.Name": "x"}}
        f1 = tmp_path / "a.json"
        f2 = tmp_path / "b.json"
        f1.write_text(json.dumps(d), encoding="utf-8")
        f2.write_text(json.dumps(d), encoding="utf-8")

        rc = diff_ods_tests(
            server1_cfg=None,
            server2_cfg=None,
            entity_name="TestStep",
            inst1_condition=None,
            inst2_condition=None,
            result_file=str(tmp_path / "result.json"),
            dump_dictionaries=False,
            exclude_regex_paths=[],
            exclude_paths=[],
            no_bulk=True,
            bulk_progress_bar=False,
            file1_path=str(f1),
            file2_path=str(f2),
        )
        assert rc == 0

    def test_mixed_file_and_server(self, tmp_path: Path, basic_server_cfg: ServerConfig) -> None:
        """One side from file, other from server."""
        import json

        d = {"E": {"E.Name": "x", "E.Value": 1}}
        f1 = tmp_path / "baseline.json"
        f1.write_text(json.dumps(d), encoding="utf-8")

        mock_con_i = MagicMock()
        with (
            patch("odsbox_diff.diff.create_connection") as mock_create,
            patch("odsbox_diff.diff.collect", return_value=(d, {})) as mock_collect,
        ):
            mock_create.return_value.__enter__ = MagicMock(return_value=mock_con_i)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            rc = diff_ods_tests(
                server1_cfg=None,
                server2_cfg=basic_server_cfg,
                entity_name="TestStep",
                inst1_condition=None,
                inst2_condition=42,
                result_file=str(tmp_path / "result.json"),
                dump_dictionaries=False,
                exclude_regex_paths=[],
                exclude_paths=[],
                no_bulk=True,
                bulk_progress_bar=False,
                file1_path=str(f1),
                file2_path=None,
            )

        assert rc == 0
        mock_create.assert_called_once_with(basic_server_cfg)
        mock_collect.assert_called_once()

    def test_dump_dictionaries_skips_file_side(self, tmp_path: Path) -> None:
        """When dump_dictionaries=True, file-based sides should not be re-written."""
        import json

        d1 = {"E": {"E.Name": "a"}}
        d2 = {"E": {"E.Name": "b"}}
        f1 = tmp_path / "inst1.json"
        f1.write_text(json.dumps(d1), encoding="utf-8")
        f2 = tmp_path / "inst2.json"
        f2.write_text(json.dumps(d2), encoding="utf-8")
        result_file = str(tmp_path / "result.json")

        diff_ods_tests(
            server1_cfg=None,
            server2_cfg=None,
            entity_name="TestStep",
            inst1_condition=None,
            inst2_condition=None,
            result_file=result_file,
            dump_dictionaries=True,
            exclude_regex_paths=[],
            exclude_paths=[],
            no_bulk=True,
            bulk_progress_bar=False,
            file1_path=str(f1),
            file2_path=str(f2),
        )

        # Dump files should NOT be created (both sides are file-based)
        assert not Path(f"{result_file}.inst1.json").exists()
        assert not Path(f"{result_file}.inst2.json").exists()


class TestCollectOdsTest:
    def test_collect_only_no_validate(self, tmp_path: Path, basic_server_cfg: ServerConfig) -> None:
        d = {"E": {"E.Name": "x"}}
        mock_con_i = MagicMock()
        output = str(tmp_path / "output.json")

        with (
            patch("odsbox_diff.diff.create_connection") as mock_create,
            patch("odsbox_diff.diff.collect", return_value=(d, {})),
            patch("odsbox_diff.diff.save_collect_results") as mock_save,
        ):
            mock_create.return_value.__enter__ = MagicMock(return_value=mock_con_i)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            rc = collect_ods_test(
                server_cfg=basic_server_cfg,
                entity_name="TestStep",
                inst_id=5,
                output_file=output,
                no_bulk=True,
                bulk_progress_bar=False,
                validate=False,
            )

        assert rc == 0
        mock_save.assert_called_once_with(output, d)

    def test_collect_validate_clean(self, tmp_path: Path, basic_server_cfg: ServerConfig) -> None:
        d = {"E": {"E.Name": "x"}}
        mock_con_i = MagicMock()
        output = str(tmp_path / "output.json")

        with (
            patch("odsbox_diff.diff.create_connection") as mock_create,
            patch("odsbox_diff.diff.collect", return_value=(d, {})),
            patch("odsbox_diff.diff.save_collect_results"),
            patch("odsbox_diff.diff.load_collect_results", return_value=d),
        ):
            mock_create.return_value.__enter__ = MagicMock(return_value=mock_con_i)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            rc = collect_ods_test(
                server_cfg=basic_server_cfg,
                entity_name="TestStep",
                inst_id=5,
                output_file=output,
                no_bulk=True,
                bulk_progress_bar=False,
                validate=True,
                validate_result_file=str(tmp_path / "validate.json"),
            )

        assert rc == 0

    def test_collect_validate_diff_found(self, tmp_path: Path, basic_server_cfg: ServerConfig) -> None:
        d = {"E": {"E.Name": "x"}}
        d_modified = {"E": {"E.Name": "y"}}
        mock_con_i = MagicMock()
        output = str(tmp_path / "output.json")
        validate_file = str(tmp_path / "validate.json")

        with (
            patch("odsbox_diff.diff.create_connection") as mock_create,
            patch("odsbox_diff.diff.collect", return_value=(d, {})),
            patch("odsbox_diff.diff.save_collect_results"),
            patch("odsbox_diff.diff.load_collect_results", return_value=d_modified),
        ):
            mock_create.return_value.__enter__ = MagicMock(return_value=mock_con_i)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            rc = collect_ods_test(
                server_cfg=basic_server_cfg,
                entity_name="TestStep",
                inst_id=5,
                output_file=output,
                no_bulk=True,
                bulk_progress_bar=False,
                validate=True,
                validate_result_file=validate_file,
            )

        assert rc == 100


class TestCreateConfig:
    def test_create_config_default_generates_three_servers_and_queries(self, tmp_path: Path) -> None:
        output = tmp_path / "generated.toml"

        created = create_config_file(str(output))
        assert created == output

        text = output.read_text(encoding="utf-8")
        assert "--config generated.toml" in text
        assert "exclude_regex_paths = [\n" in text
        assert "[servers.default]\nurl =" in text
        assert '# password = "admin"               # prefer keyring over plaintext!' in text
        assert "#   keyring set odsbox-diff http://localhost:57481/api:admin" in text
        assert (
            "#   keyring set odsbox-diff https://auth.example.com/realms/myrealm/protocol/openid-connect/token:f0a8cec0-e980-48c4-9898-8a11f40da518"
            in text
        )
        assert "# client_secret can be stored in keyring when token_endpoint is configured." in text
        assert "# Key format: <token_endpoint>:<client_id>" in text

        raw = tomllib.loads(text)
        assert set(raw["servers"].keys()) == {"default", "production", "staging"}
        assert raw["servers"]["default"]["method"] == "basic"
        assert raw["servers"]["production"]["method"] == "m2m"
        assert raw["servers"]["staging"]["method"] == "oidc"
        assert "defaults" in raw
        assert set(raw["queries"].keys()) == {"first", "second"}

    def test_create_config_single_auth_minimal_no_queries(self, tmp_path: Path) -> None:
        output = tmp_path / "single-auth.toml"

        create_config_file(
            str(output),
            single_auth="m2m",
            with_queries=False,
            include_example_comments=False,
        )

        text = output.read_text(encoding="utf-8")
        assert "#" not in text

        raw = tomllib.loads(text)
        assert set(raw["servers"].keys()) == {"production"}
        assert raw["servers"]["production"]["method"] == "m2m"
        assert "queries" not in raw

    def test_create_config_minimal_multiline_defaults_and_conditions(self, tmp_path: Path) -> None:
        output = tmp_path / "minimal.toml"

        create_config_file(
            str(output),
            include_example_comments=False,
            with_queries=True,
        )

        text = output.read_text(encoding="utf-8")
        assert "exclude_regex_paths = [\n" in text
        assert "[queries.first]\ncondition = '''{\n" in text

        raw = tomllib.loads(text)
        assert "exclude_regex_paths" in raw["defaults"]
        assert "queries" in raw

    def test_create_config_force_required_for_overwrite(self, tmp_path: Path) -> None:
        output = tmp_path / "existing.toml"
        output.write_text('[defaults]\nresult_file = "x.json"\n', encoding="utf-8")

        with pytest.raises(FileExistsError):
            create_config_file(str(output))

        create_config_file(str(output), force=True, single_auth="basic")
        raw = tomllib.loads(output.read_text(encoding="utf-8"))
        assert set(raw["servers"].keys()) == {"default"}

    def test_cli_create_config_existing_file_returns_exit_1(self, tmp_path: Path) -> None:
        output = tmp_path / "existing.toml"
        output.write_text("already there", encoding="utf-8")

        with pytest.raises(SystemExit) as ex:
            _cli_create_config(["--output", str(output)])

        assert ex.value.code == 1


class TestCliHelpFlow:
    def test_top_level_help_lists_subcommands(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("sys.argv", ["odsbox-diff", "--help"]):
            with pytest.raises(SystemExit) as ex:
                cli()

        assert ex.value.code == 0
        captured = capsys.readouterr()
        assert "diff" in captured.out
        assert "collect" in captured.out
        assert "config" in captured.out
        assert "COMMAND" in captured.out

    def test_unknown_subcommand_lists_valid_choices(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("sys.argv", ["odsbox-diff", "unknown"]):
            with pytest.raises(SystemExit) as ex:
                cli()

        assert ex.value.code == 2
        captured = capsys.readouterr()
        assert "invalid choice" in captured.err
        assert "diff" in captured.err
        assert "collect" in captured.err
        assert "config" in captured.err

    def test_explicit_diff_help_uses_diff_parser(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("sys.argv", ["odsbox-diff", "diff", "--help"]):
            with pytest.raises(SystemExit) as ex:
                cli()

        assert ex.value.code == 0
        captured = capsys.readouterr()
        assert "--entity" in captured.out
        assert "-id1" in captured.out
        assert "odsbox-diff diff" in captured.out

    def test_no_args_prints_top_level_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("sys.argv", ["odsbox-diff"]):
            with pytest.raises(SystemExit) as ex:
                cli()

        assert ex.value.code == 1
        captured = capsys.readouterr()
        assert "COMMAND" in captured.out
        assert "collect" in captured.out

    def test_implicit_diff_invocation_still_works(self, tmp_path: Path) -> None:
        defaults = SimpleNamespace(
            verbose=False,
            quiet=False,
            result_file=str(tmp_path / "default-result.json"),
            dump_dictionaries=False,
            no_bulk=False,
            bulk_progress_bar=False,
            exclude_regex_paths=[],
            exclude_paths=[],
            cached_related=[],
        )
        app_config = SimpleNamespace(defaults=defaults, servers={"default": MagicMock()}, queries=None)

        with (
            patch(
                "sys.argv", ["odsbox-diff", "--config", "cfg.toml", "--entity", "TestStep", "-id1", "1", "-id2", "2"]
            ),
            patch("odsbox_diff.diff.load_config", return_value=app_config),
            patch("odsbox_diff.diff.diff_ods_tests", return_value=0) as mock_diff,
        ):
            with pytest.raises(SystemExit) as ex:
                cli()

        assert ex.value.code == 0
        assert mock_diff.call_count == 1
