"""Configuration models for ODS server connections."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AuthMethod(Enum):
    BASIC = "basic"
    M2M = "m2m"
    OIDC = "oidc"


@dataclass
class ServerConfig:
    """Connection and authentication settings for a single ODS server."""

    url: str
    auth_method: AuthMethod = AuthMethod.BASIC
    verify_certificate: bool = True

    # basic auth
    username: str | None = None
    password: str | None = None

    # m2m / oidc shared
    client_id: str | None = None
    client_secret: str | None = None
    token_endpoint: str | None = None
    scope: list[str] | None = None

    # oidc specific
    redirect_uri: str | None = None
    redirect_url_allow_insecure: bool = False
    authorization_endpoint: str | None = None
    login_timeout: int = 60
    webfinger_path_prefix: str = ""

    def validate(self) -> None:
        """Raise ValueError if required fields for the chosen auth method are missing."""
        if not self.url:
            raise ValueError("Server URL is required.")

        if self.auth_method == AuthMethod.BASIC:
            if not self.username:
                raise ValueError("Username is required for basic auth.")
            if not self.password:
                raise ValueError(
                    f"Password is required for basic auth. "
                    f"Store it in keyring service 'odsbox-diff' with key '{self.url}:{self.username}' "
                    f"or provide it in the config file."
                )

        elif self.auth_method == AuthMethod.M2M:
            if not self.client_id:
                raise ValueError("client_id is required for m2m auth.")
            if not self.token_endpoint:
                raise ValueError("token_endpoint is required for m2m auth.")
            if not self.client_secret:
                raise ValueError(
                    f"client_secret is required for m2m auth. "
                    f"Store it in keyring service 'odsbox-diff' with key '{self.token_endpoint}:{self.client_id}' "
                    f"or provide it in the config file."
                )

        elif self.auth_method == AuthMethod.OIDC:
            if not self.client_id:
                raise ValueError("client_id is required for oidc auth.")
            if not self.redirect_uri:
                raise ValueError("redirect_uri is required for oidc auth.")


@dataclass
class DiffDefaults:
    """Default diff behavior settings loadable from config."""

    exclude_regex_paths: list[str] = field(default_factory=list[str])
    exclude_paths: list[str] = field(default_factory=list[str])
    bulk_progress_bar: bool = False
    no_bulk: bool = False
    dump_dictionaries: bool = False
    result_file: str = "diff_ods_tests_result.json"
    verbose: bool = False
    quiet: bool = False
    cached_related: list[str] = field(default_factory=list[str])


@dataclass
class AppConfig:
    """Top-level application config combining named server(s) and diff settings."""

    servers: dict[str, ServerConfig]
    defaults: DiffDefaults = field(default_factory=DiffDefaults)
    queries: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
