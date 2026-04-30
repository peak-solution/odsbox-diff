"""Config file loading, validation, and keyring-backed secret resolution."""

from __future__ import annotations

import json
import logging
import tomllib
from pathlib import Path
from typing import Any

import keyring

from .config import AppConfig, AuthMethod, DiffDefaults, ServerConfig

_KEYRING_SERVICE = "odsbox-diff"

log = logging.getLogger(__name__)


def _keyring_key_for_basic(url: str, username: str) -> str:
    return f"{url}:{username}"


def _keyring_key_for_client(token_endpoint: str, client_id: str) -> str:
    return f"{token_endpoint}:{client_id}"


def _resolve_secret(cfg: ServerConfig) -> None:
    """Fill in missing secrets from keyring. Mutates *cfg* in place."""
    if cfg.auth_method == AuthMethod.BASIC and not cfg.password:
        if cfg.username:
            key = _keyring_key_for_basic(cfg.url, cfg.username)
            secret = keyring.get_password(_KEYRING_SERVICE, key)
            if secret:
                log.debug("Resolved password from keyring for key '%s'.", key)
                cfg.password = secret

    elif cfg.auth_method in (AuthMethod.M2M, AuthMethod.OIDC) and not cfg.client_secret:
        if cfg.client_id and cfg.token_endpoint:
            key = _keyring_key_for_client(cfg.token_endpoint, cfg.client_id)
            secret = keyring.get_password(_KEYRING_SERVICE, key)
            if secret:
                log.debug("Resolved client_secret from keyring for key '%s'.", key)
                cfg.client_secret = secret


def _parse_server(raw: dict[str, Any]) -> ServerConfig:
    """Build a ServerConfig from a merged server/auth section dict."""
    auth_method_str = raw.get("method", "basic")
    try:
        auth_method = AuthMethod(auth_method_str)
    except ValueError:
        raise ValueError(f"Unknown auth method '{auth_method_str}'. Use one of: basic, m2m, oidc.")

    scope_raw = raw.get("scope")
    scope = scope_raw if isinstance(scope_raw, list) else None

    return ServerConfig(
        url=raw.get("url", ""),
        auth_method=auth_method,
        verify_certificate=raw.get("verify_certificate", True),
        username=raw.get("username"),
        password=raw.get("password"),
        client_id=raw.get("client_id"),
        client_secret=raw.get("client_secret"),
        token_endpoint=raw.get("token_endpoint"),
        scope=scope,
        redirect_uri=raw.get("redirect_uri"),
        redirect_url_allow_insecure=raw.get("redirect_url_allow_insecure", False),
        authorization_endpoint=raw.get("authorization_endpoint"),
        login_timeout=raw.get("login_timeout", 60),
        webfinger_path_prefix=raw.get("webfinger_path_prefix", ""),
    )


def _parse_config(raw: dict[str, Any]) -> AppConfig:
    """Build an AppConfig from a parsed TOML/JSON dictionary."""
    servers: dict[str, ServerConfig] = {}

    if "servers" in raw:
        # New format: one [servers.<name>] section per server
        for name, srv_raw in raw["servers"].items():
            if isinstance(srv_raw, dict):
                servers[name] = _parse_server(srv_raw)
    elif "server" in raw:
        # New format: single unnamed [server] section
        servers["default"] = _parse_server(raw["server"])
    elif "connection" in raw or "authentication" in raw:
        # Backward-compat: old separate [connection] + [authentication] sections
        conn = raw.get("connection", {})
        auth = raw.get("authentication", {})
        servers["default"] = _parse_server({**conn, **auth})
    # else: no server section — allowed when both diff sides are file sources
    # and only [defaults] is needed from the config.

    defaults_raw = raw.get("defaults", {})
    erp = defaults_raw.get("exclude_regex_paths", [])
    ep = defaults_raw.get("exclude_paths", [])
    cr = defaults_raw.get("cached_related", [])
    defaults = DiffDefaults(
        exclude_regex_paths=erp if isinstance(erp, list) else [],
        exclude_paths=ep if isinstance(ep, list) else [],
        bulk_progress_bar=defaults_raw.get("bulk_progress_bar", False),
        no_bulk=defaults_raw.get("no_bulk", False),
        dump_dictionaries=defaults_raw.get("dump_dictionaries", False),
        result_file=defaults_raw.get("result_file", "diff_ods_tests_result.json"),
        verbose=defaults_raw.get("verbose", False),
        quiet=defaults_raw.get("quiet", False),
        cached_related=cr if isinstance(cr, list) else [],
    )

    queries: list[dict[str, Any]] = []
    for query_name, query_raw in raw.get("queries", {}).items():
        if isinstance(query_raw, dict) and "condition" in query_raw:
            condition_raw = query_raw["condition"]
            condition = json.loads(condition_raw) if isinstance(condition_raw, str) else condition_raw
            queries.append({"name": query_name, "condition": condition})

    return AppConfig(servers=servers, defaults=defaults, queries=queries)


def load_config(path: str | Path) -> AppConfig:
    """Load, validate, and return an AppConfig from a TOML or JSON file.

    Secrets missing from the file are resolved from the OS keyring before
    validation so that the returned config is ready for connection creation.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Config file not found: {p}")

    text = p.read_text(encoding="utf-8")

    if p.suffix in (".toml",):
        raw = tomllib.loads(text)
    elif p.suffix in (".json",):
        raw = json.loads(text)
    else:
        # Try TOML first, fall back to JSON
        try:
            raw = tomllib.loads(text)
        except Exception:
            raw = json.loads(text)

    app_config = _parse_config(raw)
    for cfg in app_config.servers.values():
        _resolve_secret(cfg)
        cfg.validate()

    return app_config
