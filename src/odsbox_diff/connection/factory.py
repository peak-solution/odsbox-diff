"""Create ConI connections from ServerConfig using odsbox ConIFactory."""

from __future__ import annotations

import logging

from odsbox import ConI
from odsbox import ConIFactory

from .config import AuthMethod, ServerConfig

log = logging.getLogger(__name__)


def create_connection(cfg: ServerConfig) -> ConI:
    """Return an opened ConI for the given server configuration."""
    log.debug("Creating %s connection to %s", cfg.auth_method.value, cfg.url)

    if cfg.auth_method == AuthMethod.BASIC:
        return ConIFactory.basic(
            url=cfg.url,
            username=cfg.username,  # type: ignore[arg-type]
            password=cfg.password,  # type: ignore[arg-type]
            verify_certificate=cfg.verify_certificate,
        )

    if cfg.auth_method == AuthMethod.M2M:
        return ConIFactory.m2m(
            url=cfg.url,
            token_endpoint=cfg.token_endpoint,  # type: ignore[arg-type]
            client_id=cfg.client_id,  # type: ignore[arg-type]
            client_secret=cfg.client_secret,  # type: ignore[arg-type]
            scope=cfg.scope,
            verify_certificate=cfg.verify_certificate,
        )

    if cfg.auth_method == AuthMethod.OIDC:
        return ConIFactory.oidc(
            url=cfg.url,
            client_id=cfg.client_id,  # type: ignore[arg-type]
            redirect_uri=cfg.redirect_uri,  # type: ignore[arg-type]
            redirect_url_allow_insecure=cfg.redirect_url_allow_insecure,
            client_secret=cfg.client_secret,
            scope=cfg.scope,
            authorization_endpoint=cfg.authorization_endpoint,
            token_endpoint=cfg.token_endpoint,
            login_timeout=cfg.login_timeout,
            verify_certificate=cfg.verify_certificate,
            webfinger_path_prefix=cfg.webfinger_path_prefix,
        )

    raise ValueError(f"Unsupported auth method: {cfg.auth_method}")
