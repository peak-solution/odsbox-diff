"""Connection subsystem: config models, config loading, and connection factory."""

from .config import AppConfig, AuthMethod, DiffDefaults, ServerConfig
from .factory import create_connection
from .manager import load_config

__all__ = [
    "AppConfig",
    "AuthMethod",
    "DiffDefaults",
    "ServerConfig",
    "create_connection",
    "load_config",
]
