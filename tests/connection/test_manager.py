"""Tests for connection.manager: parsing and loading config."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from odsbox_diff.connection.config import AuthMethod
from odsbox_diff.connection.manager import (
    _keyring_key_for_basic,
    _keyring_key_for_client,
    _parse_config,
    _parse_server,
    load_config,
)


class TestKeyringKeys:
    def test_basic(self) -> None:
        assert _keyring_key_for_basic("http://x/api", "alice") == "http://x/api:alice"

    def test_client(self) -> None:
        assert _keyring_key_for_client("http://t", "cid") == "http://t:cid"


class TestParseServer:
    def test_basic(self) -> None:
        cfg = _parse_server({"url": "http://x", "method": "basic", "username": "u", "password": "p"})
        assert cfg.url == "http://x"
        assert cfg.auth_method == AuthMethod.BASIC
        assert cfg.username == "u"
        assert cfg.password == "p"
        assert cfg.verify_certificate is True

    def test_m2m(self) -> None:
        cfg = _parse_server(
            {
                "url": "http://x",
                "method": "m2m",
                "client_id": "c",
                "token_endpoint": "http://t",
                "scope": ["s1"],
            }
        )
        assert cfg.auth_method == AuthMethod.M2M
        assert cfg.scope == ["s1"]

    def test_oidc(self) -> None:
        cfg = _parse_server(
            {
                "url": "http://x",
                "method": "oidc",
                "client_id": "c",
                "redirect_uri": "http://127.0.0.1",
                "login_timeout": 30,
                "webfinger_path_prefix": "/ods",
            }
        )
        assert cfg.auth_method == AuthMethod.OIDC
        assert cfg.login_timeout == 30
        assert cfg.webfinger_path_prefix == "/ods"

    def test_unknown_method(self) -> None:
        with pytest.raises(ValueError, match="Unknown auth method"):
            _parse_server({"method": "ldap"})

    def test_default_method_is_basic(self) -> None:
        cfg = _parse_server({"url": "http://x"})
        assert cfg.auth_method == AuthMethod.BASIC

    def test_scope_non_list_ignored(self) -> None:
        cfg = _parse_server({"url": "http://x", "method": "m2m", "scope": "not-a-list"})
        assert cfg.scope is None


class TestParseConfig:
    def test_single_server(self, raw_basic_config: dict[str, object]) -> None:
        app = _parse_config(raw_basic_config)
        assert "default" in app.servers
        assert app.servers["default"].url == "http://localhost:8080/api"
        assert app.defaults.result_file == "out.json"
        assert app.defaults.exclude_regex_paths == [r"\.Foo'\]$"]
        assert app.defaults.exclude_paths == ["root['x']"]

    def test_multi_server(self, raw_multi_server_config: dict[str, object]) -> None:
        app = _parse_config(raw_multi_server_config)
        assert set(app.servers.keys()) == {"prod", "staging"}

    def test_servers_default_single_server(self) -> None:
        app = _parse_config(
            {
                "servers": {
                    "default": {
                        "url": "http://localhost:8080/api",
                        "method": "basic",
                        "username": "admin",
                        "password": "secret",
                    }
                }
            }
        )
        assert set(app.servers.keys()) == {"default"}
        assert app.servers["default"].url == "http://localhost:8080/api"

    def test_servers_default_with_named_servers(self) -> None:
        app = _parse_config(
            {
                "servers": {
                    "default": {"url": "http://x", "username": "u", "password": "p"},
                    "staging": {"url": "http://s", "username": "u", "password": "p"},
                }
            }
        )
        assert set(app.servers.keys()) == {"default", "staging"}

    def test_legacy_connection_authentication(self) -> None:
        raw = {
            "connection": {"url": "http://x", "verify_certificate": False},
            "authentication": {"method": "basic", "username": "u", "password": "p"},
        }
        app = _parse_config(raw)
        assert "default" in app.servers
        assert app.servers["default"].url == "http://x"
        assert app.servers["default"].verify_certificate is False
        assert app.servers["default"].username == "u"

    def test_empty_config_produces_empty_servers(self) -> None:
        # No server/servers/connection sections -> empty servers dict is allowed
        # (e.g. config with only [defaults] for file-to-file diffs).
        app = _parse_config({})
        assert app.servers == {}

    def test_defaults_section_optional(self) -> None:
        app = _parse_config({"server": {"url": "http://x", "username": "u", "password": "p"}})
        assert app.defaults.result_file == "diff_ods_tests_result.json"
        assert app.defaults.cached_related == []

    def test_defaults_non_list_falls_back(self) -> None:
        app = _parse_config(
            {
                "server": {"url": "http://x"},
                "defaults": {"exclude_regex_paths": "not-a-list", "cached_related": 123},
            }
        )
        assert app.defaults.exclude_regex_paths == []
        assert app.defaults.cached_related == []

    def test_queries_parsed_from_config(self) -> None:
        raw = {
            "queries": {
                "first": {"condition": '{"Name": "Step A", "parent_test.name": "Run 1"}'},
                "second": {"condition": '{"Name": "Step B"}'},
            }
        }
        app = _parse_config(raw)
        assert len(app.queries) == 2
        names = {q["name"] for q in app.queries}
        assert names == {"first", "second"}
        first = next(q for q in app.queries if q["name"] == "first")
        assert first["condition"] == {"Name": "Step A", "parent_test.name": "Run 1"}

    def test_queries_dict_condition_passthrough(self) -> None:
        """condition may already be a dict (e.g. parsed from JSON config)."""
        raw = {
            "queries": {
                "q1": {"condition": {"Name": "Step A"}},
            }
        }
        app = _parse_config(raw)
        assert app.queries[0]["condition"] == {"Name": "Step A"}

    def test_no_queries_section_gives_empty_list(self) -> None:
        app = _parse_config({})
        assert app.queries == []


class TestLoadConfig:
    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nope.toml")

    def test_load_toml(self, tmp_path: Path) -> None:
        p = tmp_path / "c.toml"
        p.write_text(
            """
[server]
url = "http://x"
method = "basic"
username = "u"
password = "p"
""",
            encoding="utf-8",
        )
        with patch("odsbox_diff.connection.manager.keyring") as kr:
            kr.get_password.return_value = None
            app = load_config(p)
        assert app.servers["default"].url == "http://x"

    def test_load_json(self, tmp_path: Path) -> None:
        p = tmp_path / "c.json"
        p.write_text(
            json.dumps(
                {
                    "server": {
                        "url": "http://x",
                        "method": "basic",
                        "username": "u",
                        "password": "p",
                    }
                }
            ),
            encoding="utf-8",
        )
        with patch("odsbox_diff.connection.manager.keyring") as kr:
            kr.get_password.return_value = None
            app = load_config(p)
        assert app.servers["default"].username == "u"

    def test_keyring_resolves_basic_password(self, tmp_path: Path) -> None:
        p = tmp_path / "c.toml"
        p.write_text(
            """
[server]
url = "http://x"
method = "basic"
username = "u"
""",
            encoding="utf-8",
        )
        with patch("odsbox_diff.connection.manager.keyring") as kr:
            kr.get_password.return_value = "from-keyring"
            app = load_config(p)
        assert app.servers["default"].password == "from-keyring"

    def test_validation_failure(self, tmp_path: Path) -> None:
        p = tmp_path / "c.toml"
        p.write_text(
            """
[server]
url = "http://x"
method = "basic"
username = "u"
""",
            encoding="utf-8",
        )
        with patch("odsbox_diff.connection.manager.keyring") as kr:
            kr.get_password.return_value = None
            with pytest.raises(ValueError, match="[Pp]assword"):
                load_config(p)
