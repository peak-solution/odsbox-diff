"""diff tool to compare two tests, test steps or measurements"""

import argparse
import json
import logging
import sys
from typing import Any, cast

import urllib3

from deepdiff import DeepDiff

from .connection import ServerConfig, create_connection, load_config
from .ods_diff_hierarchy.collect import collect, load_collect_results, save_collect_results
from .ods_diff_hierarchy.diff import diff_dictionaries, dump_diff_as_json

urllib3.disable_warnings()


def _parse_id_string(id_string: str | int, queries: list[dict[str, Any]] | None) -> int | dict[str, Any] | str:
    if isinstance(id_string, str):
        if id_string.isdigit():
            return int(id_string)

        query_string: str | None = None
        if id_string.strip().startswith("{") and id_string.strip().endswith("}"):
            query_string = id_string.strip()
        else:
            if queries:
                for query in queries:
                    if query.get("name") == id_string:
                        query_string = cast(str, query.get("condition"))
        if not query_string:
            raise ValueError(f"ID string '{id_string}' is not a valid integer, JSON condition, or named query.")

        try:
            logging.warning("*** Parsing JSON condition string: %s", query_string)
            if isinstance(query_string, dict):
                return query_string
            return json.loads(query_string)  # type: ignore
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON condition string: {id_string}") from e
    elif isinstance(id_string, dict):
        return id_string
    else:
        return int(id_string)


def _parse_server_id(
    id_str: str, servers: dict[str, ServerConfig], queries: list[dict[str, Any]] | None, multi_server: bool
) -> tuple[ServerConfig, int | str | dict[str, Any]]:
    """Parse 'server:id' or 'id' format, returning (ServerConfig, id_int).

    Args:
        id_str: String like '5' or 'prod:5'
        servers: Available servers dict
        multi_server: True if multiple servers configured

    Raises:
        ValueError: If format is invalid or server not found
    """
    if ":" in id_str and not id_str.strip().startswith("{"):
        server_name, id_part = id_str.split(":", 1)
        if server_name not in servers:
            raise ValueError(f"Server '{server_name}' not found. Available: {', '.join(servers.keys())}")
        try:
            instance_id = _parse_id_string(id_part, queries)
        except ValueError:
            raise ValueError(f"Invalid ID '{id_part}' after colon; must be an integer, JSON condition, or named query.")
        return servers[server_name], instance_id
    else:
        if multi_server:
            raise ValueError(
                f"Multiple servers configured ({', '.join(servers.keys())}). "
                f"Specify server as 'server:id' (e.g., 'prod:5')."
            )
        sole = next(iter(servers.values()))
        try:
            instance_id = _parse_id_string(id_str, queries)
        except ValueError:
            raise ValueError(f"Invalid ID '{id_str}'; must be an integer")
        return sole, instance_id


def _parse_id_or_file(
    id_str: str, servers: dict[str, ServerConfig], queries: list[dict[str, Any]] | None, multi_server: bool
) -> tuple[ServerConfig | None, int | str | dict[str, Any] | None, str | None]:
    """Parse an instance reference that may be a file path or a server:id.

    Args:
        id_str: One of ``"file:path.json"``, ``"42"``, or ``"server:42"``.
        servers: Available servers dict (may be empty for file sources).
        multi_server: True if multiple servers configured.

    Returns:
        ``(None, None, file_path)`` when the input starts with ``file:``,
        otherwise ``(ServerConfig, instance_id, None)`` via :func:`_parse_server_id`.
    """
    if id_str.startswith("file:"):
        return None, None, id_str[5:]
    cfg, iid = _parse_server_id(id_str, servers, queries, multi_server)
    return cfg, iid, None


def diff_ods_tests(
    server1_cfg: ServerConfig | None,
    server2_cfg: ServerConfig | None,
    entity_name: str,
    inst1_condition: int | str | dict[str, Any] | None,
    inst2_condition: int | str | dict[str, Any] | None,
    result_file: str,
    dump_dictionaries: bool,
    exclude_regex_paths: list[str],
    exclude_paths: list[str],
    no_bulk: bool,
    bulk_progress_bar: bool,
    cached_related: list[str] | None = None,
    file1_path: str | None = None,
    file2_path: str | None = None,
) -> int:
    """Collect two ODS hierarchies and write a structural diff to ``result_file``.

    Each side can be collected live from a server (when ``server*_cfg`` and
    ``inst*_id`` are given) or loaded from a previously saved JSON/ZIP file
    (when ``file*_path`` is given).

    Args:
        server1_cfg: Configuration for the server hosting ``inst1_id``.
            ``None`` when loading side 1 from a file.
        server2_cfg: Configuration for the server hosting ``inst2_id``.
            ``None`` when loading side 2 from a file.  May be the same object
            as ``server1_cfg`` to reuse a single connection.
        entity_name: ODS entity name (e.g. ``"TestStep"``) of the root instances.
        inst1_id: Instance ID on ``server1_cfg``. ``None`` when using a file.
        inst2_id: Instance ID on ``server2_cfg``. ``None`` when using a file.
        result_file: Path to write the diff JSON to. If empty, no file is written.
        dump_dictionaries: Also write each collected hierarchy as
            ``<result_file>.inst1.json`` / ``.inst2.json``.
        exclude_regex_paths: Extra regex patterns appended to the default exclusions.
        exclude_paths: Extra explicit DeepDiff paths to exclude.
        no_bulk: If ``True``, skip hashing of bulk LocalColumn data.
        bulk_progress_bar: Show a textual progress bar during bulk hashing.
        cached_related: Entity names whose IDs should be resolved to names in the
            output for cleaner diffs.
        file1_path: Path to a previously saved hierarchy JSON/ZIP for side 1.
            When set, ``server1_cfg`` and ``inst1_id`` are ignored.
        file2_path: Path to a previously saved hierarchy JSON/ZIP for side 2.
            When set, ``server2_cfg`` and ``inst2_id`` are ignored.

    Returns:
        ``0`` if no differences were found, ``100`` if differences were found.
    """
    log = logging.getLogger(__name__)
    log.info("Comparing '%s' id=%s vs id=%s", entity_name, inst1_condition or file1_path, inst2_condition or file2_path)

    inst1_dict = None
    inst2_dict = None

    # --- Side 1 ---
    if file1_path is not None:
        log.info("[1/2] ------- Loading from file: %s", file1_path)
        inst1_dict = load_collect_results(file1_path)
        log.info("[1/2] ------- Loaded from file.")
    # --- Side 2 ---
    if file2_path is not None:
        log.info("[2/2] ------- Loading from file: %s", file2_path)
        inst2_dict = load_collect_results(file2_path)
        log.info("[2/2] ------- Loaded from file.")

    # --- Server-based collection for sides that are NOT file-based ---
    if inst1_dict is None or inst2_dict is None:
        # Determine which sides need server collection
        need_1 = inst1_dict is None
        need_2 = inst2_dict is None
        same_server = need_1 and need_2 and server1_cfg is server2_cfg

        if same_server:
            assert server1_cfg is not None
            log.info("Connecting to server: %s", server1_cfg.url)
            with create_connection(server1_cfg) as con_i:
                if need_1:
                    assert inst1_condition is not None
                    log.info("[1/2] ------- Collecting '%s' id=%s ...", entity_name, inst1_condition)
                    inst1_dict = collect(
                        con_i,
                        entity_name,
                        inst1_condition,
                        calculate_bulk_hash=not no_bulk,
                        show_progress=bulk_progress_bar,
                        cached_related_entities=cached_related,
                    )[0]
                    log.info("[1/2] ------- Finished collecting '%s' id=%s.", entity_name, inst1_condition)
                if need_2:
                    assert inst2_condition is not None
                    log.info("[2/2] ------- Collecting '%s' id=%s ...", entity_name, inst2_condition)
                    inst2_dict = collect(
                        con_i,
                        entity_name,
                        inst2_condition,
                        calculate_bulk_hash=not no_bulk,
                        show_progress=bulk_progress_bar,
                        cached_related_entities=cached_related,
                    )[0]
                    log.info("[2/2] ------- Finished collecting '%s' id=%s.", entity_name, inst2_condition)
            log.info("Connection closed")
        else:
            if need_1:
                assert server1_cfg is not None
                assert inst1_condition is not None
                log.info("Connecting to server1: %s", server1_cfg.url)
                with create_connection(server1_cfg) as con_i1:
                    log.info("[1/2] ------- Collecting '%s' id=%s ...", entity_name, inst1_condition)
                    inst1_dict = collect(
                        con_i1,
                        entity_name,
                        inst1_condition,
                        calculate_bulk_hash=not no_bulk,
                        show_progress=bulk_progress_bar,
                        cached_related_entities=cached_related,
                    )[0]
                    log.info("[1/2] ------- Finished collecting '%s' id=%s.", entity_name, inst1_condition)
                log.info("Connection to server1 closed")
            if need_2:
                assert server2_cfg is not None
                assert inst2_condition is not None
                log.info("Connecting to server2: %s", server2_cfg.url)
                with create_connection(server2_cfg) as con_i2:
                    log.info("[2/2] ------- Collecting '%s' id=%s ...", entity_name, inst2_condition)
                    inst2_dict = collect(
                        con_i2,
                        entity_name,
                        inst2_condition,
                        calculate_bulk_hash=not no_bulk,
                        show_progress=bulk_progress_bar,
                        cached_related_entities=cached_related,
                    )[0]
                    log.info("[2/2] ------- Finished collecting '%s' id=%s.", entity_name, inst2_condition)
                log.info("Connection to server2 closed")

    if dump_dictionaries and result_file is not None and "" != result_file:
        log.info("Dumping collected dictionaries alongside result file")
        if file1_path is None:
            with open(f"{result_file}.inst1.json", "w", encoding="utf-8") as f:
                json.dump(inst1_dict, f, indent=2, default=str)
        if file2_path is None:
            with open(f"{result_file}.inst2.json", "w", encoding="utf-8") as f:
                json.dump(inst2_dict, f, indent=2, default=str)

    assert inst1_dict is not None
    assert inst2_dict is not None
    log.info("Running diff ...")
    diff_result: DeepDiff = diff_dictionaries(inst1_dict, inst2_dict, exclude_regex_paths, exclude_paths)

    if not diff_result:
        log.info("Result: no differences found")
    else:
        n = sum(len(v) if hasattr(v, "__len__") else 1 for v in diff_result.values())
        log.info("Result: %s difference(s) found", n)

    if result_file is not None and "" != result_file:
        log.info("Writing result file: %s", result_file)
        dump_diff_as_json(result_file, diff_result)

    return 0 if not diff_result else 100


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odsbox-diff",
        description="Compare two Hierarchy instances of an ASAM ODS server and write a difference result file.",
        epilog="Returns 0 if no changes where found.",
    )
    parser.add_argument(
        "-c",
        "--config",
        dest="config",
        type=str,
        required=True,
        help="Path to TOML or JSON config file with server connection and default settings.",
    )
    parser.add_argument(
        "-entity",
        "--entity",
        dest="entity_name",
        type=str,
        required=True,
        nargs="?",
        help="Entity to collect instance tree for.",
    )
    parser.add_argument(
        "-id1",
        "--inst1_id",
        dest="inst1_id",
        type=str,
        required=True,
        nargs="?",
        help="Instance ID ('42'), 'server:id' ('prod:5'), or 'file:path.json' to load from disk.",
    )
    parser.add_argument(
        "-id2",
        "--inst2_id",
        dest="inst2_id",
        type=str,
        required=True,
        nargs="?",
        help="Instance ID ('42'), 'server:id' ('staging:5'), or 'file:path.json' to load from disk.",
    )
    parser.add_argument(
        "-rf",
        "--result_file",
        dest="result_file",
        help="File storing the results if Tests differs. Overrides config default.",
        default=None,
    )
    parser.add_argument(
        "-ep",
        "--exclude_path",
        dest="exclude_paths",
        type=str,
        action="append",
        help="Add path to exclude from diff. Can be used multiple times. Extends config defaults.",
    )
    parser.add_argument(
        "-erp",
        "--exclude_regex_path",
        dest="exclude_regex_paths",
        type=str,
        action="append",
        help="Add regex to exclude paths from diff. Can be used multiple times. Extends config defaults.",
    )
    parser.add_argument(
        "-dd",
        "--dump_dictionaries",
        dest="dump_dictionaries",
        action="store_true",
        default=None,
        help="Dump collected dictionaries to JSON files alongside the result file.",
    )
    parser.add_argument("-v", "--verbose", dest="verbose", action="store_true", default=None)
    parser.add_argument(
        "-q",
        "--quiet",
        dest="quiet",
        action="store_true",
        default=None,
        help="Suppress all output.",
    )
    parser.add_argument(
        "-bn",
        "--no_bulk",
        dest="no_bulk",
        action="store_true",
        default=None,
        help="If given the bulk values are not hashed.",
    )
    parser.add_argument(
        "-bpb",
        "--bulk_progress_bar",
        dest="bulk_progress_bar",
        action="store_true",
        default=None,
        help="Show a progress bar while calculating bulk hash values.",
    )
    parser.add_argument(
        "--cached-related",
        dest="cached_related",
        type=str,
        nargs="+",
        default=None,
        metavar="ENTITY",
        help="Entity names whose IDs are resolved to names in the diff output (e.g. AoUnit Classification). Extends config defaults.",
    )
    return parser


def cli() -> None:
    """Console script entry point for ``uv run odsbox-diff``.

    Parses CLI arguments, loads the config file, applies CLI-over-config
    precedence to all options, resolves ``server:id`` instance references and
    delegates to :func:`diff_ods_tests`. Exits with the diff return code
    (``0`` no differences, ``100`` differences found, ``-1`` on uncaught
    exception, ``1`` on argument validation errors).
    """
    # Dispatch to collect subcommand if requested
    if len(sys.argv) > 1 and sys.argv[1] == "collect":
        _cli_collect(sys.argv[2:])
        return

    parser = _build_parser()
    args = parser.parse_args()

    # Load config (connection + defaults)
    app_config = load_config(args.config)
    defaults = app_config.defaults

    # CLI-over-config precedence: explicit CLI flags override config defaults
    verbose = args.verbose if args.verbose is not None else defaults.verbose
    quiet = args.quiet if args.quiet is not None else defaults.quiet
    if quiet:
        logging.disable(logging.CRITICAL)
    elif verbose:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    result_file = args.result_file if args.result_file is not None else defaults.result_file
    dump_dicts = args.dump_dictionaries if args.dump_dictionaries is not None else defaults.dump_dictionaries
    no_bulk = args.no_bulk if args.no_bulk is not None else defaults.no_bulk
    bulk_progress_bar = args.bulk_progress_bar if args.bulk_progress_bar is not None else defaults.bulk_progress_bar

    # Extend config defaults with any extra CLI exclusions
    exclude_regex_paths = list(defaults.exclude_regex_paths)
    if args.exclude_regex_paths:
        exclude_regex_paths.extend(args.exclude_regex_paths)

    exclude_paths = list(defaults.exclude_paths)
    if args.exclude_paths:
        exclude_paths.extend(args.exclude_paths)

    cached_related = list(defaults.cached_related)
    if args.cached_related:
        cached_related.extend(args.cached_related)

    log = logging.getLogger(__name__)

    # Resolve server configs and instance IDs from 'server:id' or 'file:path' format
    servers = app_config.servers
    multi_server = len(servers) > 1
    queries = app_config.queries

    try:
        server1_cfg, inst1_condition, file1_path = _parse_id_or_file(args.inst1_id, servers, queries, multi_server)
        server2_cfg, inst2_condition, file2_path = _parse_id_or_file(args.inst2_id, servers, queries, multi_server)
    except ValueError as e:
        log.error("%s", e)
        sys.exit(1)

    try:
        return_value = diff_ods_tests(
            server1_cfg=server1_cfg,
            server2_cfg=server2_cfg,
            entity_name=args.entity_name,
            inst1_condition=inst1_condition,
            inst2_condition=inst2_condition,
            result_file=result_file,
            dump_dictionaries=dump_dicts,
            exclude_regex_paths=exclude_regex_paths,
            exclude_paths=exclude_paths,
            no_bulk=no_bulk,
            bulk_progress_bar=bulk_progress_bar,
            cached_related=cached_related,
            file1_path=file1_path,
            file2_path=file2_path,
        )
        log.info("Finished with result code: %s", return_value)
        sys.exit(return_value)
    except Exception as e:
        log.exception("Exception: %s", e)
        sys.exit(-1)


def collect_ods_test(
    server_cfg: ServerConfig,
    entity_name: str,
    inst_id: int | str | dict[str, Any],
    output_file: str,
    no_bulk: bool,
    bulk_progress_bar: bool,
    cached_related: list[str] | None = None,
    validate: bool = False,
    validate_result_file: str = "collect_validate_result.json",
) -> int:
    """Collect an ODS hierarchy and save it to a file.

    Optionally performs a round-trip validation by reloading the file and
    diffing it against the in-memory data.

    Args:
        server_cfg: Configuration for the server to collect from.
        entity_name: ODS entity name (e.g. ``"TestStep"``).
        inst_id: Instance ID to collect.
        output_file: Path to write the collected hierarchy (``.json`` or ``.zip``).
        no_bulk: If ``True``, skip hashing of bulk LocalColumn data.
        bulk_progress_bar: Show a progress bar during bulk hashing.
        cached_related: Entity names whose IDs should be resolved to names.
        validate: If ``True``, reload the saved file and self-diff to verify
            round-trip fidelity.
        validate_result_file: Path to write the self-diff result when
            ``validate=True``.

    Returns:
        ``0`` if successful (or self-diff found no differences),
        ``100`` if self-diff found unexpected differences.
    """
    log = logging.getLogger(__name__)
    log.info("Collecting '%s' id=%s from %s", entity_name, inst_id, server_cfg.url)

    with create_connection(server_cfg) as con_i:
        result_dict = collect(
            con_i,
            entity_name,
            inst_id,
            calculate_bulk_hash=not no_bulk,
            show_progress=bulk_progress_bar,
            cached_related_entities=cached_related,
        )[0]
    log.info("Connection closed")

    log.info("Saving collected hierarchy to: %s", output_file)
    save_collect_results(output_file, result_dict)

    if not validate:
        return 0

    log.info("Validating round-trip fidelity ...")
    reloaded = load_collect_results(output_file)
    diff_result: DeepDiff = diff_dictionaries(reloaded, result_dict, [], [])

    if not diff_result:
        log.info("Validation passed: no differences after round-trip.")
        return 0
    else:
        n = sum(len(v) if hasattr(v, "__len__") else 1 for v in diff_result.values())
        log.warning("Validation found %s unexpected difference(s)!", n)
        dump_diff_as_json(validate_result_file, diff_result)
        log.info("Self-diff written to: %s", validate_result_file)
        return 100


def _build_collect_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odsbox-diff collect",
        description="Collect an ODS instance hierarchy and save it to a JSON or ZIP file.",
    )
    parser.add_argument(
        "-c",
        "--config",
        dest="config",
        type=str,
        required=True,
        help="Path to TOML or JSON config file with server connection and default settings.",
    )
    parser.add_argument(
        "-entity",
        "--entity",
        dest="entity_name",
        type=str,
        required=True,
        help="Entity to collect instance tree for.",
    )
    parser.add_argument(
        "-id",
        "--inst_id",
        dest="inst_id",
        type=str,
        required=True,
        help="Instance ID or 'server:id' (e.g. 'prod:42').",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        type=str,
        required=True,
        help="Output file path (.json or .zip).",
    )
    parser.add_argument(
        "--validate",
        dest="validate",
        action="store_true",
        default=False,
        help="After saving, reload and self-diff to verify round-trip fidelity.",
    )
    parser.add_argument(
        "-rf",
        "--result_file",
        dest="result_file",
        help="File storing the self-diff result when --validate is used.",
        default="collect_validate_result.json",
    )
    parser.add_argument(
        "-bn",
        "--no_bulk",
        dest="no_bulk",
        action="store_true",
        default=None,
        help="If given the bulk values are not hashed.",
    )
    parser.add_argument(
        "-bpb",
        "--bulk_progress_bar",
        dest="bulk_progress_bar",
        action="store_true",
        default=None,
        help="Show a progress bar while calculating bulk hash values.",
    )
    parser.add_argument("-v", "--verbose", dest="verbose", action="store_true", default=None)
    parser.add_argument(
        "-q",
        "--quiet",
        dest="quiet",
        action="store_true",
        default=None,
        help="Suppress all output.",
    )
    parser.add_argument(
        "--cached-related",
        dest="cached_related",
        type=str,
        nargs="+",
        default=None,
        metavar="ENTITY",
        help="Entity names whose IDs are resolved to names in the output.",
    )
    return parser


def _cli_collect(raw_args: list[str]) -> None:
    """Parse and execute the ``odsbox-diff collect`` subcommand."""
    parser = _build_collect_parser()
    args = parser.parse_args(raw_args)

    app_config = load_config(args.config)
    defaults = app_config.defaults

    verbose = args.verbose if args.verbose is not None else defaults.verbose
    quiet = args.quiet if args.quiet is not None else defaults.quiet
    if quiet:
        logging.disable(logging.CRITICAL)
    elif verbose:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    no_bulk = args.no_bulk if args.no_bulk is not None else defaults.no_bulk
    bulk_progress_bar = args.bulk_progress_bar if args.bulk_progress_bar is not None else defaults.bulk_progress_bar

    cached_related = list(defaults.cached_related)
    if args.cached_related:
        cached_related.extend(args.cached_related)

    log = logging.getLogger(__name__)

    servers = app_config.servers
    multi_server = len(servers) > 1

    queries = app_config.queries

    try:
        server_cfg, inst_id = _parse_server_id(args.inst_id, servers, queries, multi_server)
    except ValueError as e:
        log.error("%s", e)
        sys.exit(1)

    try:
        return_value = collect_ods_test(
            server_cfg=server_cfg,
            entity_name=args.entity_name,
            inst_id=inst_id,
            output_file=args.output,
            no_bulk=no_bulk,
            bulk_progress_bar=bulk_progress_bar,
            cached_related=cached_related,
            validate=args.validate,
            validate_result_file=args.result_file,
        )
        log.info("Finished with result code: %s", return_value)
        sys.exit(return_value)
    except Exception as e:
        log.exception("Exception: %s", e)
        sys.exit(-1)


if __name__ == "__main__":
    cli()
