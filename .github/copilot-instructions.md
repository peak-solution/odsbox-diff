# Copilot Instructions — odsbox-diff

## What this project is

CLI + library that compares two ASAM ODS instance hierarchies (typically
`TestStep` or `Measurement`) on one or two servers and produces a structured
JSON diff. Built on `odsbox` (ODS access) and `deepdiff` (comparison).

## Architecture

```
src/odsbox_diff/
  __init__.py              # re-exports: high-level API + building blocks
  __main__.py              # python -m odsbox_diff -> diff.cli()
  api.py                   # High-level API: diff_file_to_file, diff_server_to_server,
                           #   diff_file_to_server, collect_to_file, _resolve_config
  diff.py                  # CLI argparse, _parse_server_id, _parse_id_or_file,
                           #   diff_ods_tests, collect_ods_test, cli, _cli_collect
  connection/
    config.py              # ServerConfig / DiffDefaults / AppConfig dataclasses, AuthMethod enum
    manager.py             # _parse_server, _parse_config, load_config, keyring lookups
    factory.py             # create_connection: ServerConfig -> odsbox.ConI
  ods_diff_hierarchy/
    collect.py             # Collector class + collect() + save_/load_collect_results
    diff.py                # diff_dictionaries (DeepDiff wrapper) + dump_diff_as_json
    rel_to_name.py         # RelToName: cache entity ID -> name lookups for cleaner diffs
```

## Conventions & invariants

- **Auth methods**: `AuthMethod.BASIC`, `AuthMethod.M2M`, `AuthMethod.OIDC`.
  Each has its own required-field set enforced by `ServerConfig.validate()`.
- **Secrets**: never stored in code or required in config; resolved from the
  OS keyring under service `odsbox-diff`. Keys are
  `<url>:<username>` (basic) or `<token_endpoint>:<client_id>` (m2m/oidc).
- **CLI-over-config precedence**: every CLI flag has `default=None`; `cli()`
  applies `args.x if args.x is not None else defaults.x`. List options
  (exclude paths, cached_related) extend rather than replace defaults.
- **Multi-server**: instance IDs use `server:id` format. With a single
  configured server, plain integers are accepted. See `_parse_server_id` in
  `diff.py`.
- **File sources**: instance IDs prefixed with `file:` (e.g. `file:baseline.json`)
  load a previously saved hierarchy from disk instead of connecting to a server.
  See `_parse_id_or_file` in `diff.py`.
- **Collect subcommand**: `odsbox-diff collect` saves a hierarchy snapshot to a
  file. With `--validate`, a round-trip self-diff is performed.
- **API vs CLI boundary**: `api.py` functions return `DeepDiff` objects and
  raise exceptions — no `sys.exit()`. CLI code in `diff.py` translates
  `DeepDiff` results into exit codes. `_resolve_config` in `api.py` accepts
  `str | Path | AppConfig`, allowing callers to bypass config files entirely.
- **Exit codes**: `0` no diff, `100` diff found, `1` arg/validation error,
  `-1` uncaught exception.
- **Default DeepDiff exclusions**: `.Id`, `.DateCreated`, `.Version` regex
  exclusions are always applied (in `ods_diff_hierarchy/diff.py`); user
  exclusions extend them.
- **Logging**: each module uses a module-level `_log = logging.getLogger(__name__)`.
  Methods alias it locally (`log = _log`) to keep call sites short.
- **Persistence**: `save_collect_results` accepts `.json` or `.zip`. ZIP
  contains `result.json`, optional `info.txt`, and any extra files added by
  basename.
- **Empty servers allowed**: `load_config()` tolerates configs with no
  `[server]` section — only `[defaults]` is needed for file-to-file diffs.

## Testing

- Test framework: pytest (configured in `pyproject.toml`).
- `tests/` mirrors `src/odsbox_diff/`.
- `ConI` and other ODS-server interactions are mocked with
  `unittest.mock.MagicMock` (see `tests/ods_diff_hierarchy/test_rel_to_name.py`).
- Live ODS integration tests are out of scope; focus on:
  - Pure helpers (`_join_path`, `_hash_pandas_row`, keyring key builders).
  - Config parsing (`_parse_server`, `_parse_config`, `load_config` with
    keyring patched).
  - DeepDiff behavior with default and custom exclusions.
  - `save/load_collect_results` JSON and ZIP roundtrips.
- Run: `uv run pytest`.

## Tooling

- `uv` for dependency management.
- `ruff` (line-length 120) for lint/format.
- `mypy --strict` for type checking; `# type: ignore[arg-type]` is used in
  `connection/factory.py` only because `odsbox` factory functions don't
  accept `Optional` for credential fields and `ServerConfig.validate()`
  guarantees they are set.

## When adding code

- Add a unit test alongside any new pure helper or parsing logic.
- Don't introduce new logger objects per call; reuse the module-level `_log`.
- Don't write JSON results inline — use `dump_diff_as_json()` or
  `save_collect_results()`.
- Preserve the CLI-over-config precedence pattern when adding new options:
  set CLI `default=None` and add a matching `DiffDefaults` field.
- New high-level programmatic helpers belong in `api.py`, not `diff.py`.
  `api.py` functions return `DeepDiff` and raise exceptions; `diff.py`
  contains CLI plumbing that calls `sys.exit()`.
