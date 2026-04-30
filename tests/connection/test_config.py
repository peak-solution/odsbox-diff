"""Tests for ServerConfig.validate() and AuthMethod."""

from __future__ import annotations

import pytest

from odsbox_diff.connection.config import AppConfig, AuthMethod, DiffDefaults, ServerConfig


class TestAuthMethod:
    def test_values(self) -> None:
        assert AuthMethod("basic") is AuthMethod.BASIC
        assert AuthMethod("m2m") is AuthMethod.M2M
        assert AuthMethod("oidc") is AuthMethod.OIDC

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError):
            AuthMethod("unknown")


class TestBasicValidate:
    def test_valid_passes(self, basic_server_cfg: ServerConfig) -> None:
        basic_server_cfg.validate()

    def test_missing_url(self) -> None:
        cfg = ServerConfig(url="", auth_method=AuthMethod.BASIC, username="u", password="p")
        with pytest.raises(ValueError, match="URL"):
            cfg.validate()

    def test_missing_username(self) -> None:
        cfg = ServerConfig(url="http://x", auth_method=AuthMethod.BASIC, password="p")
        with pytest.raises(ValueError, match="[Uu]sername"):
            cfg.validate()

    def test_missing_password(self) -> None:
        cfg = ServerConfig(url="http://x", auth_method=AuthMethod.BASIC, username="u")
        with pytest.raises(ValueError, match="[Pp]assword"):
            cfg.validate()


class TestM2MValidate:
    def test_valid_passes(self, m2m_server_cfg: ServerConfig) -> None:
        m2m_server_cfg.validate()

    def test_missing_client_id(self) -> None:
        cfg = ServerConfig(
            url="http://x",
            auth_method=AuthMethod.M2M,
            token_endpoint="http://t",
            client_secret="s",
        )
        with pytest.raises(ValueError, match="client_id"):
            cfg.validate()

    def test_missing_token_endpoint(self) -> None:
        cfg = ServerConfig(
            url="http://x",
            auth_method=AuthMethod.M2M,
            client_id="c",
            client_secret="s",
        )
        with pytest.raises(ValueError, match="token_endpoint"):
            cfg.validate()

    def test_missing_client_secret(self) -> None:
        cfg = ServerConfig(
            url="http://x",
            auth_method=AuthMethod.M2M,
            client_id="c",
            token_endpoint="http://t",
        )
        with pytest.raises(ValueError, match="client_secret"):
            cfg.validate()


class TestOIDCValidate:
    def test_valid_passes(self, oidc_server_cfg: ServerConfig) -> None:
        oidc_server_cfg.validate()

    def test_missing_client_id(self) -> None:
        cfg = ServerConfig(
            url="http://x",
            auth_method=AuthMethod.OIDC,
            redirect_uri="http://127.0.0.1",
        )
        with pytest.raises(ValueError, match="client_id"):
            cfg.validate()

    def test_missing_redirect_uri(self) -> None:
        cfg = ServerConfig(
            url="http://x",
            auth_method=AuthMethod.OIDC,
            client_id="c",
        )
        with pytest.raises(ValueError, match="redirect_uri"):
            cfg.validate()


class TestDataclassDefaults:
    def test_diff_defaults(self) -> None:
        d = DiffDefaults()
        assert d.exclude_regex_paths == []
        assert d.exclude_paths == []
        assert d.cached_related == []
        assert d.bulk_progress_bar is False
        assert d.no_bulk is False
        assert d.dump_dictionaries is False
        assert d.result_file == "diff_ods_tests_result.json"
        assert d.verbose is False
        assert d.quiet is False

    def test_app_config(self, basic_server_cfg: ServerConfig) -> None:
        app = AppConfig(servers={"default": basic_server_cfg})
        assert app.servers["default"] is basic_server_cfg
        assert isinstance(app.defaults, DiffDefaults)
