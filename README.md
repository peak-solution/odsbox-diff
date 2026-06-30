# odsbox-diff

[![Build](https://github.com/peak-solution/odsbox-diff/actions/workflows/build.yml/badge.svg)](https://github.com/peak-solution/odsbox-diff/actions/workflows/build.yml)
[![PyPI version](https://img.shields.io/pypi/v/odsbox-diff.svg)](https://pypi.org/project/odsbox-diff/)
[![Python versions](https://img.shields.io/pypi/pyversions/odsbox-diff.svg)](https://pypi.org/project/odsbox-diff/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

A CLI and Python library to compare two instance hierarchies on one or two ASAM ODS
servers and write a structured diff result. Built on
[odsbox](https://pypi.org/project/odsbox/) for ODS access and
[deepdiff](https://pypi.org/project/deepdiff/) for the comparison.

Typical use cases:

- Verify that a test, test step or measurement was migrated faithfully between
  two servers.
- Detect unintended changes between two snapshots of the same instance.
- Hash bulk LocalColumn data to detect changes in measured signals.
- **Regression testing** — compare a saved baseline file against a live server
  instance.
- **Create baselines** — collect a hierarchy snapshot to a file for later
  comparison, with optional round-trip validation.
- **Offline comparison** — diff two previously saved hierarchy files without
  any server connection.

> **Full user guide:** see [`docs/usage.md`](docs/usage.md) for comprehensive
> CLI examples, Python API reference, pytest integration patterns, and
> troubleshooting.

## Installation

```powershell
uv add odsbox-diff
# or, with pip
pip install odsbox-diff
```

The package requires Python 3.14+ and ships a console script `odsbox-diff`.

Run `uv run odsbox-diff --help` to see the available commands (`diff`, `collect`,
and `config`). Use `uv run odsbox-diff COMMAND --help` for command-specific
options.

## Quick start

1. Create a starter config:

  ```powershell
  uv run odsbox-diff config
  ```

  Default output is `./odsbox-diff.config.toml` with three use-case server
  entries: `default` (basic), `production` (m2m), and `staging` (oidc).

  Or copy one of the example configs from `configs/` and adjust it:

   - `config.example.toml` — basic auth (single or multiple servers)
   - `config.m2m.example.toml` — OAuth2 machine-to-machine
   - `config.oidc.example.toml` — OIDC (interactive browser login)

2. Store the secret (password / `client_secret`) in your OS keyring (see
   [Keyring secrets](#keyring-secrets) below) or inline it in the config file.

3. Run the diff:

   ```powershell
  uv run odsbox-diff diff `
       --config my-config.toml `
       --entity TestStep `
       -id1 5 `
       -id2 7
   ```

   With multiple named servers, prefix instance IDs with the server name:

   ```powershell
     uv run odsbox-diff diff `
       --config my-config.toml `
       --entity TestStep `
       -id1 prod:1898 `
       -id2 staging:2
   ```

   Compare two saved JSON files (no server connection needed):

   ```powershell
     uv run odsbox-diff diff `
       --config my-config.toml `
       --entity TestStep `
       -id1 file:baseline.json `
       -id2 file:current.json
   ```

     The historical form without the explicit `diff` subcommand still works for
     backward compatibility.

   Collect a hierarchy to a file and self-validate:

   ```powershell
   uv run odsbox-diff collect `
       --config my-config.toml `
       --entity TestStep `
       -id 42 `
       -o baseline.json `
       --validate
   ```

## CLI reference

### `odsbox-diff diff` (recommended diff mode)

| Flag | Description |
| --- | --- |
| `-c`, `--config` | Path to a TOML or JSON config file (required). |
| `--entity` | Root entity name to compare (e.g. `TestStep`, `Measurement`). |
| `-id1` / `-id2` | Instance reference: plain ID (`42`), `server:id` (`prod:5`), or `file:path.json` to load from disk. |
| `-rf`, `--result_file` | Override the result-file path from config defaults. |
| `-ep`, `--exclude_path` | Extra DeepDiff path to exclude (repeatable). |
| `-erp`, `--exclude_regex_path` | Extra regex path exclusion (repeatable). |
| `-dd`, `--dump_dictionaries` | Also dump the collected hierarchies as `<result>.inst1.json` / `.inst2.json`. |
| `-bn`, `--no_bulk` | Skip bulk LocalColumn hashing. |
| `-bpb`, `--bulk_progress_bar` | Show a progress bar during bulk hashing. |
| `--cached-related ENTITY [...]` | Resolve relation IDs to names for the listed entities. |
| `-v`, `--verbose` | INFO logging with timestamps. |
| `-q`, `--quiet` | Suppress all logging. |

CLI flags always override config defaults. List options (`exclude_path`,
`exclude_regex_path`, `cached-related`) extend the config defaults rather than
replacing them.

For backward compatibility, `odsbox-diff --config ... --entity ... -id1 ... -id2 ...`
still runs the diff command implicitly.

### `odsbox-diff collect` (collect mode)

| Flag | Description |
| --- | --- |
| `-c`, `--config` | Path to a TOML or JSON config file (required). |
| `--entity` | Root entity name to collect. |
| `-id` | Instance ID or `server:id`. |
| `-o`, `--output` | Output file path (`.json` or `.zip`). |
| `--validate` | After saving, reload and self-diff to verify round-trip fidelity. |
| `-rf`, `--result_file` | Path for the self-diff result (only with `--validate`). |
| `-bn`, `--no_bulk` | Skip bulk LocalColumn hashing. |
| `-bpb`, `--bulk_progress_bar` | Show a progress bar during bulk hashing. |
| `--cached-related ENTITY [...]` | Resolve relation IDs to names. |
| `-v`, `--verbose` | INFO logging with timestamps. |
| `-q`, `--quiet` | Suppress all logging. |

### `odsbox-diff config` (config scaffolding)

| Flag | Description |
| --- | --- |
| `-o`, `--output` | Output path (default: `./odsbox-diff.config.toml`). |
| `--force` | Overwrite output file if it already exists. |
| `--single-auth {basic,m2m,oidc}` | Generate only one server section. |
| `--with-queries` / `--no-queries` | Include or skip `queries.first` and `queries.second`. |
| `--include-example-comments` / `--minimal` | Verbose guided output or compact output without comments. |

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | No differences found (or collect completed successfully). |
| `100` | Differences found; result file written. |
| `1` | Argument or `server:id` validation error. |
| `-1` | Uncaught exception. |

## Keyring secrets

Secrets are read from the OS keyring under the service name `odsbox-diff`:

| Auth method | Keyring key |
| --- | --- |
| `basic` | `<url>:<username>` (password) |
| `m2m` / `oidc` | `<token_endpoint>:<client_id>` (`client_secret`) |

Example with the `keyring` CLI:

```powershell
keyring set odsbox-diff "http://localhost:57481/api:admin"
```

## Library usage

### High-level API (recommended for test frameworks)

```python
from odsbox_diff import diff_file_to_file, diff_file_to_server, collect_to_file
from odsbox_diff.connection import AppConfig, ServerConfig, AuthMethod

# Compare two saved files — no server needed
diff = diff_file_to_file("baseline.json", "current.json")
assert not diff  # falsy = no differences

# Regression test: baseline file vs live server
diff = diff_file_to_server("my-config.toml", "TestStep", 42, "baseline.json")
assert not diff

# Build config in code (no config file needed)
cfg = AppConfig(servers={"default": ServerConfig(
    url="http://localhost:8080/api",
    username="admin",
    password="secret",
)})
diff = diff_file_to_server(cfg, "TestStep", 42, "baseline.json")

# Collect a baseline and validate round-trip fidelity
result = collect_to_file("my-config.toml", "TestStep", 42, "baseline.json", validate=True)
assert not result  # falsy = round-trip is clean
```

### Low-level building blocks

```python
from odsbox_diff import (
    collect,
    diff_dictionaries,
    dump_diff_as_json,
    save_collect_results,
)
from odsbox_diff.connection import create_connection, load_config

app_config = load_config("my-config.toml")
server = next(iter(app_config.servers.values()))

with create_connection(server) as con_i:
    tree_a, _ = collect(con_i, "TestStep", 5)
    tree_b, _ = collect(con_i, "TestStep", 7)

diff = diff_dictionaries(tree_a, tree_b, [], [])
dump_diff_as_json("diff.json", diff)
```

## Configuration reference

### `[server]` / `[servers.<name>]`

Either a single `[server]` table (stored internally as the `default` server) or
one `[servers.<name>]` table per named server. Common fields:

For single-server usage, `[servers.default]` is supported and behaves the same
as `[server]`.

| Field | Type | Notes |
| --- | --- | --- |
| `url` | string | ODS REST endpoint (required). |
| `verify_certificate` | bool | Default `true`. |
| `method` | string | `basic`, `m2m`, or `oidc`. Default `basic`. |

Method-specific fields are documented in the example configs in `configs/`.

When using file-to-file comparisons only, the `[server]` section can be omitted
entirely — only `[defaults]` is needed.

### `[defaults]`

Optional defaults for diff behavior:

| Field | Type | Default |
| --- | --- | --- |
| `result_file` | string | `"diff_ods_tests_result.json"` |
| `exclude_paths` | list | `[]` |
| `exclude_regex_paths` | list | `[]` (default `Id` / `DateCreated` / `Version` exclusions are always applied) |
| `cached_related` | list | `[]` |
| `bulk_progress_bar` | bool | `false` |
| `no_bulk` | bool | `false` |
| `dump_dictionaries` | bool | `false` |
| `verbose` | bool | `false` |
| `quiet` | bool | `false` |

## Development

```powershell
uv sync
uv run pytest
uv run ruff check src tests
uv run mypy src
```
