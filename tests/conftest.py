"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from odsbox_diff.connection.config import AuthMethod, ServerConfig


@pytest.fixture
def basic_server_cfg() -> ServerConfig:
    return ServerConfig(
        url="http://localhost:8080/api",
        auth_method=AuthMethod.BASIC,
        username="admin",
        password="secret",
    )


@pytest.fixture
def m2m_server_cfg() -> ServerConfig:
    return ServerConfig(
        url="https://srv.example.com/api",
        auth_method=AuthMethod.M2M,
        client_id="client-1",
        client_secret="shh",
        token_endpoint="https://auth.example.com/token",
        scope=["machine2machine"],
    )


@pytest.fixture
def oidc_server_cfg() -> ServerConfig:
    return ServerConfig(
        url="https://srv.example.com/api",
        auth_method=AuthMethod.OIDC,
        client_id="client-1",
        redirect_uri="http://127.0.0.1:1234",
    )


@pytest.fixture
def raw_basic_config() -> dict[str, object]:
    return {
        "server": {
            "url": "http://localhost:8080/api",
            "method": "basic",
            "username": "admin",
            "password": "secret",
        },
        "defaults": {
            "result_file": "out.json",
            "exclude_regex_paths": [r"\.Foo'\]$"],
            "exclude_paths": ["root['x']"],
        },
    }


@pytest.fixture
def raw_multi_server_config() -> dict[str, object]:
    return {
        "servers": {
            "prod": {
                "url": "https://prod.example.com/api",
                "method": "basic",
                "username": "u",
                "password": "p",
            },
            "staging": {
                "url": "https://staging.example.com/api",
                "method": "basic",
                "username": "u",
                "password": "p",
            },
        },
    }
