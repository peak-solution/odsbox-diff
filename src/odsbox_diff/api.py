"""High-level API for programmatic use in test frameworks and scripts.

All functions return :class:`~deepdiff.DeepDiff` objects (falsy when no
differences are found) and raise exceptions on errors — no ``sys.exit()``
calls.  This makes them suitable for direct use in ``assert`` statements::

    from odsbox_diff import diff_file_to_file
    assert not diff_file_to_file("baseline.json", "current.json")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from deepdiff import DeepDiff

from .connection import AppConfig, ServerConfig, create_connection, load_config
from .ods_diff_hierarchy.collect import collect, load_collect_results, save_collect_results
from .ods_diff_hierarchy.diff import diff_dictionaries

_log = logging.getLogger(__name__)


def _resolve_config(config: str | Path | AppConfig) -> AppConfig:
    """Return an :class:`AppConfig`, loading from disk when needed."""
    if isinstance(config, AppConfig):
        return config
    return load_config(str(config))


def _resolve_server_and_id(
    config: AppConfig,
    inst_id: int | str,
) -> tuple[ServerConfig, int | str | dict[str, Any]]:
    """Resolve a server config and instance condition from *inst_id*.

    *inst_id* may be a plain ``int``, a string integer (``"42"``),
    a JSON condition string, a named query, or ``"server:42"`` for
    multi-server configs.
    """
    from .diff import _parse_server_id

    servers = config.servers
    multi_server = len(servers) > 1
    return _parse_server_id(str(inst_id), servers, config.queries, multi_server)


def _collect_from_server(
    server_cfg: ServerConfig,
    entity_name: str,
    inst_id: int | str | dict[str, Any],
    *,
    no_bulk: bool = False,
    bulk_progress_bar: bool = False,
    cached_related: list[str] | None = None,
) -> dict[Any, Any]:
    """Connect to an ODS server and collect a hierarchy."""
    log = _log
    log.info("Connecting to %s", server_cfg.url)
    with create_connection(server_cfg) as con_i:
        result, _ = collect(
            con_i,
            entity_name,
            inst_id,
            calculate_bulk_hash=not no_bulk,
            show_progress=bulk_progress_bar,
            cached_related_entities=cached_related,
        )
    log.info("Connection closed")
    return result


# ── Public API ───────────────────────────────────────────────────────────


def diff_file_to_file(
    file1: str | Path,
    file2: str | Path,
    *,
    exclude_regex_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
) -> DeepDiff:
    """Compare two previously saved hierarchy files.

    No server connection or config file is required.

    Args:
        file1: Path to the first hierarchy JSON or ZIP file.
        file2: Path to the second hierarchy JSON or ZIP file.
        exclude_regex_paths: Extra regex exclusions appended to the defaults.
        exclude_paths: Extra explicit path exclusions.

    Returns:
        A :class:`~deepdiff.DeepDiff` object.  Falsy when no differences exist.
    """
    d1 = load_collect_results(str(file1))
    d2 = load_collect_results(str(file2))
    return diff_dictionaries(
        d1,
        d2,
        exclude_regex_paths or [],
        exclude_paths or [],
    )


def diff_server_to_server(
    config: str | Path | AppConfig,
    entity_name: str,
    inst1_id: int | str,
    inst2_id: int | str,
    *,
    exclude_regex_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    no_bulk: bool = False,
    cached_related: list[str] | None = None,
) -> DeepDiff:
    """Collect two hierarchies from ODS server(s) and diff them.

    Args:
        config: Path to a TOML/JSON config file **or** an :class:`AppConfig`
            built in code.
        entity_name: ODS entity name (e.g. ``"TestStep"``).
        inst1_id: Instance ID or ``"server:id"`` string for the first side.
        inst2_id: Instance ID or ``"server:id"`` string for the second side.
        exclude_regex_paths: Extra regex exclusions appended to the defaults.
        exclude_paths: Extra explicit path exclusions.
        no_bulk: Skip hashing of bulk LocalColumn data.
        cached_related: Entity names whose IDs are resolved to names.

    Returns:
        A :class:`~deepdiff.DeepDiff` object.  Falsy when no differences exist.
    """
    app = _resolve_config(config)
    cfg1, id1 = _resolve_server_and_id(app, inst1_id)
    cfg2, id2 = _resolve_server_and_id(app, inst2_id)

    d1 = _collect_from_server(cfg1, entity_name, id1, no_bulk=no_bulk, cached_related=cached_related)
    d2 = _collect_from_server(cfg2, entity_name, id2, no_bulk=no_bulk, cached_related=cached_related)

    return diff_dictionaries(
        d1,
        d2,
        exclude_regex_paths or [],
        exclude_paths or [],
    )


def diff_file_to_server(
    config: str | Path | AppConfig,
    entity_name: str,
    server_id: int | str,
    baseline_file: str | Path,
    *,
    exclude_regex_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    no_bulk: bool = False,
    cached_related: list[str] | None = None,
) -> DeepDiff:
    """Compare a saved baseline file against a live server hierarchy.

    Typical use case: regression testing — verify that a server instance still
    matches a known-good baseline.

    Args:
        config: Path to a TOML/JSON config file **or** an :class:`AppConfig`.
        entity_name: ODS entity name (e.g. ``"TestStep"``).
        server_id: Instance ID or ``"server:id"`` for the live side.
        baseline_file: Path to the baseline hierarchy JSON or ZIP file.
        exclude_regex_paths: Extra regex exclusions appended to the defaults.
        exclude_paths: Extra explicit path exclusions.
        no_bulk: Skip hashing of bulk LocalColumn data.
        cached_related: Entity names whose IDs are resolved to names.

    Returns:
        A :class:`~deepdiff.DeepDiff` object.  Falsy when no differences exist.
    """
    app = _resolve_config(config)
    cfg, iid = _resolve_server_and_id(app, server_id)

    baseline = load_collect_results(str(baseline_file))
    live = _collect_from_server(cfg, entity_name, iid, no_bulk=no_bulk, cached_related=cached_related)

    return diff_dictionaries(
        baseline,
        live,
        exclude_regex_paths or [],
        exclude_paths or [],
    )


def collect_to_file(
    config: str | Path | AppConfig,
    entity_name: str,
    inst_id: int | str,
    output_file: str | Path,
    *,
    no_bulk: bool = False,
    bulk_progress_bar: bool = False,
    cached_related: list[str] | None = None,
    validate: bool = False,
) -> DeepDiff | None:
    """Collect an ODS hierarchy and save it to a JSON or ZIP file.

    When *validate* is ``True`` the file is reloaded immediately and compared
    against the in-memory data to verify round-trip fidelity.

    Args:
        config: Path to a TOML/JSON config file **or** an :class:`AppConfig`.
        entity_name: ODS entity name (e.g. ``"TestStep"``).
        inst_id: Instance ID or ``"server:id"`` string.
        output_file: Destination path (``.json`` or ``.zip``).
        no_bulk: Skip hashing of bulk LocalColumn data.
        bulk_progress_bar: Show a progress bar during bulk hashing.
        cached_related: Entity names whose IDs are resolved to names.
        validate: Perform a round-trip self-diff after saving.

    Returns:
        ``None`` when *validate* is ``False``.
        A :class:`~deepdiff.DeepDiff` object when *validate* is ``True``
        (falsy if round-trip is clean).
    """
    app = _resolve_config(config)
    cfg, iid = _resolve_server_and_id(app, inst_id)

    result = _collect_from_server(
        cfg,
        entity_name,
        iid,
        no_bulk=no_bulk,
        bulk_progress_bar=bulk_progress_bar,
        cached_related=cached_related,
    )

    out = str(output_file)
    save_collect_results(out, result)
    _log.info("Saved collected hierarchy to: %s", out)

    if not validate:
        return None

    _log.info("Validating round-trip fidelity ...")
    reloaded = load_collect_results(out)
    return diff_dictionaries(reloaded, result, [], [])
