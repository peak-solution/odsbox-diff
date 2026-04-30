# odsbox-diff User Guide

## Overview

odsbox-diff compares ASAM ODS instance hierarchies and produces structured JSON
diffs.  It works in three modes:

| Mode | Description |
| --- | --- |
| **Server-to-server** | Collect two hierarchies from ODS server(s) and diff them. |
| **File-based** | Load one or both sides from previously saved JSON/ZIP files. |
| **Collect** | Save a hierarchy snapshot to a file, optionally validating it. |

Each mode is available both via the **CLI** (`odsbox-diff` command) and the
**Python API** (importable functions for use in pytest and scripts).

---

## Installation & Setup

### Install

```powershell
uv add odsbox-diff
# or
pip install odsbox-diff
```

Requires Python 3.14+.

### Configuration file

Copy one of the example configs from `configs/` and adapt it to your
environment:

| File | Auth method |
| --- | --- |
| `config.example.toml` | Basic (username / password) |
| `config.m2m.example.toml` | OAuth2 machine-to-machine |
| `config.oidc.example.toml` | OIDC (interactive browser login) |

### Keyring secrets

Rather than storing secrets in the config file, store them in your OS keyring
under the service name `odsbox-diff`:

```powershell
# Basic auth
keyring set odsbox-diff "http://localhost:57481/api:admin"

# M2M / OIDC
keyring set odsbox-diff "https://auth.example.com/token:my-client-id"
```

| Auth method | Keyring key format |
| --- | --- |
| `basic` | `<url>:<username>` |
| `m2m` / `oidc` | `<token_endpoint>:<client_id>` |

---

## CLI: Diff Mode

The default mode compares two hierarchy instances and writes a diff result file.

### Two server instances

```powershell
uv run odsbox-diff `
    --config my-config.toml `
    --entity TestStep `
    -id1 5 `
    -id2 7
```

With multiple named servers:

```powershell
uv run odsbox-diff `
    --config my-config.toml `
    --entity TestStep `
    -id1 prod:1898 `
    -id2 staging:2
```

### Two JSON files (offline comparison)

Use the `file:` prefix to load a side from a previously saved JSON or ZIP file.
No server connection is opened for file-based sides.

```powershell
uv run odsbox-diff `
    --config my-config.toml `
    --entity TestStep `
    -id1 file:baseline.json `
    -id2 file:current.json
```

When both sides are files, the config file only needs a `[defaults]` section —
the `[server]` section can be omitted.

### Baseline file vs live server (regression test)

Mix a file source with a server source:

```powershell
uv run odsbox-diff `
    --config my-config.toml `
    --entity TestStep `
    -id1 file:baseline.json `
    -id2 42
```

### Diff mode flags

| Flag | Description |
| --- | --- |
| `-c`, `--config` | Path to TOML or JSON config file (required). |
| `-entity`, `--entity` | Root ODS entity name (e.g. `TestStep`, `Measurement`). |
| `-id1`, `-id2` | Instance reference: `42`, `server:42`, or `file:path.json`. |
| `-rf`, `--result_file` | Override the result-file path. |
| `-ep`, `--exclude_path` | Extra DeepDiff path to exclude (repeatable). |
| `-erp`, `--exclude_regex_path` | Extra regex path exclusion (repeatable). |
| `-dd`, `--dump_dictionaries` | Dump collected hierarchies as `.inst1.json` / `.inst2.json`. |
| `-bn`, `--no_bulk` | Skip bulk LocalColumn hashing. |
| `-bpb`, `--bulk_progress_bar` | Show progress bar during bulk hashing. |
| `--cached-related ENTITY [...]` | Resolve relation IDs to names. |
| `-v`, `--verbose` | INFO logging with timestamps. |
| `-q`, `--quiet` | Suppress all logging. |

CLI flags override config defaults.  List options (`-ep`, `-erp`,
`--cached-related`) **extend** rather than replace the config defaults.

---

## CLI: Collect Mode

The `collect` subcommand saves a hierarchy snapshot to a file without
performing a diff.

### Create a baseline

```powershell
uv run odsbox-diff collect `
    --config my-config.toml `
    --entity TestStep `
    -id 42 `
    -o baseline.json
```

### Create and self-validate

Add `--validate` to reload the saved file and compare it against the in-memory
data.  This confirms the JSON serialization round-trip is lossless.

```powershell
uv run odsbox-diff collect `
    --config my-config.toml `
    --entity TestStep `
    -id 42 `
    -o baseline.json `
    --validate
```

Exit code `0` means the round-trip is clean.  Exit code `100` means unexpected
differences were found (the self-diff result is written to the file specified
by `-rf`).

### Save as ZIP

Use a `.zip` extension to save the hierarchy in a compressed archive:

```powershell
uv run odsbox-diff collect `
    --config my-config.toml `
    --entity TestStep `
    -id 42 `
    -o baseline.zip `
    --validate
```

### Collect mode flags

| Flag | Description |
| --- | --- |
| `-c`, `--config` | Path to TOML or JSON config file (required). |
| `-entity`, `--entity` | Root ODS entity name. |
| `-id` | Instance ID or `server:id`. |
| `-o`, `--output` | Output file path (`.json` or `.zip`). |
| `--validate` | Reload and self-diff after saving. |
| `-rf`, `--result_file` | Path for self-diff result (default: `collect_validate_result.json`). |
| `-bn`, `--no_bulk` | Skip bulk hashing. |
| `-bpb`, `--bulk_progress_bar` | Show progress bar. |
| `--cached-related ENTITY [...]` | Resolve relation IDs to names. |
| `-v`, `--verbose` / `-q`, `--quiet` | Logging control. |

---

## Exit Codes

| Code | Meaning |
| --- | --- |
| `0` | No differences found / collect completed successfully. |
| `100` | Differences found; result file written. |
| `1` | Argument or validation error. |
| `-1` | Uncaught exception. |

---

## Config File Reference

### `[server]` / `[servers.<name>]`

Either a single `[server]` table or one `[servers.<name>]` table per named
server.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `url` | string | — | ODS REST endpoint (required). |
| `verify_certificate` | bool | `true` | Set `false` for self-signed certs. |
| `method` | string | `"basic"` | `basic`, `m2m`, or `oidc`. |
| `username` | string | — | Required for `basic`. |
| `password` | string | — | `basic` only; prefer keyring. |
| `client_id` | string | — | Required for `m2m` / `oidc`. |
| `client_secret` | string | — | `m2m` / `oidc`; prefer keyring. |
| `token_endpoint` | string | — | Required for `m2m` / `oidc`. |
| `scope` | list | — | OAuth2 scopes. |
| `redirect_uri` | string | — | Required for `oidc`. |
| `authorization_endpoint` | string | — | Optional for `oidc`. |
| `login_timeout` | int | `60` | OIDC browser timeout (seconds). |

When using file-to-file comparisons only, the `[server]` section can be omitted
entirely.

### `[defaults]`

| Field | Type | Default |
| --- | --- | --- |
| `result_file` | string | `"diff_ods_tests_result.json"` |
| `exclude_paths` | list | `[]` |
| `exclude_regex_paths` | list | `[]` |
| `cached_related` | list | `[]` |
| `bulk_progress_bar` | bool | `false` |
| `no_bulk` | bool | `false` |
| `dump_dictionaries` | bool | `false` |
| `verbose` | bool | `false` |
| `quiet` | bool | `false` |

The fields `Id`, `DateCreated`, and `Version` are **always** excluded from
diffs regardless of this configuration.

### `[queries.<name>]`

Named queries let you reference an ODS attribute condition by a short alias
instead of repeating a JSON string on the command line.

```toml
[queries.my_step]
condition = '{"Name": "Step A", "parent_test.name": "Run 1"}'
```

Use the alias as an instance ID:

```powershell
uv run odsbox-diff --config my-config.toml --entity TestStep -id1 my_step -id2 42
```

With multiple servers:

```powershell
uv run odsbox-diff --config my-config.toml --entity TestStep -id1 prod:my_step -id2 staging:my_step
```

The `condition` value may be a TOML inline table instead of a JSON string:

```toml
[queries.baseline]
condition = {Name = "Step A", "parent_test.name" = "Run 1"}
```

---

## Python API

The package provides four high-level functions designed for use in test
frameworks and automation scripts.  All return a
[`DeepDiff`](https://zepworks.com/deepdiff/) object (falsy when no differences
exist) and raise exceptions on errors — no `sys.exit()` calls.

### `diff_file_to_file`

Compare two previously saved hierarchy files.  No server connection or config
file required.

```python
from odsbox_diff import diff_file_to_file

diff = diff_file_to_file("baseline.json", "current.json")
assert not diff  # no differences
```

**Signature:**

```python
diff_file_to_file(
    file1: str | Path,
    file2: str | Path,
    *,
    exclude_regex_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
) -> DeepDiff
```

### `diff_server_to_server`

Collect two hierarchies from ODS server(s) and diff them programmatically.

```python
from odsbox_diff import diff_server_to_server

diff = diff_server_to_server("my-config.toml", "TestStep", 5, 7)
assert not diff
```

**Signature:**

```python
diff_server_to_server(
    config: str | Path | AppConfig,
    entity_name: str,
    inst1_id: int | str,
    inst2_id: int | str,
    *,
    exclude_regex_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    no_bulk: bool = False,
    cached_related: list[str] | None = None,
) -> DeepDiff
```

### `diff_file_to_server`

Compare a saved baseline against a live server hierarchy — ideal for regression
tests.

```python
from odsbox_diff import diff_file_to_server

diff = diff_file_to_server("my-config.toml", "TestStep", 42, "baseline.json")
assert not diff
```

**Signature:**

```python
diff_file_to_server(
    config: str | Path | AppConfig,
    entity_name: str,
    server_id: int | str,
    baseline_file: str | Path,
    *,
    exclude_regex_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    no_bulk: bool = False,
    cached_related: list[str] | None = None,
) -> DeepDiff
```

### `collect_to_file`

Collect a hierarchy snapshot and save it to disk.  Optionally validate the
round-trip.

```python
from odsbox_diff import collect_to_file

# Just collect
collect_to_file("my-config.toml", "TestStep", 42, "baseline.json")

# Collect and validate
result = collect_to_file("my-config.toml", "TestStep", 42, "baseline.json", validate=True)
assert not result  # round-trip is clean
```

**Signature:**

```python
collect_to_file(
    config: str | Path | AppConfig,
    entity_name: str,
    inst_id: int | str,
    output_file: str | Path,
    *,
    no_bulk: bool = False,
    bulk_progress_bar: bool = False,
    cached_related: list[str] | None = None,
    validate: bool = False,
) -> DeepDiff | None
```

Returns `None` when `validate=False`, or a `DeepDiff` object when
`validate=True` (falsy if the round-trip is clean).

### Building config in code

All API functions that accept a `config` parameter take either a file path or
an `AppConfig` object built directly in Python — no config file on disk needed:

```python
from odsbox_diff import diff_file_to_server
from odsbox_diff.connection import AppConfig, ServerConfig

cfg = AppConfig(servers={"default": ServerConfig(
    url="http://localhost:8080/api",
    username="admin",
    password="secret",
)})

diff = diff_file_to_server(cfg, "TestStep", 42, "baseline.json")
assert not diff
```

---

## Using with pytest

Here is a complete example of a regression test suite using odsbox-diff:

```python
"""tests/test_regression.py — ODS regression tests."""

import pytest
from odsbox_diff import collect_to_file, diff_file_to_server
from odsbox_diff.connection import AppConfig, ServerConfig

CONFIG = AppConfig(servers={"default": ServerConfig(
    url="http://localhost:8080/api",
    username="admin",
    password="secret",
)})

BASELINE_DIR = "tests/baselines"


@pytest.fixture(scope="session")
def create_baseline(tmp_path_factory):
    """One-time baseline creation (run with --create-baselines flag)."""
    out = tmp_path_factory.mktemp("baselines") / "step42.json"
    result = collect_to_file(CONFIG, "TestStep", 42, out, validate=True)
    assert not result, "Baseline round-trip validation failed!"
    return out


def test_teststep_42_unchanged():
    """Verify TestStep 42 still matches the committed baseline."""
    diff = diff_file_to_server(
        CONFIG,
        "TestStep",
        42,
        f"{BASELINE_DIR}/step42.json",
    )
    assert not diff, f"Regression detected:\n{diff.to_json(indent=2)}"


def test_two_baselines_identical():
    """Compare two saved baselines (no server needed)."""
    from odsbox_diff import diff_file_to_file

    diff = diff_file_to_file(
        f"{BASELINE_DIR}/step42_v1.json",
        f"{BASELINE_DIR}/step42_v2.json",
    )
    assert not diff
```

---

## Understanding Diff Output

The result file is standard [DeepDiff](https://zepworks.com/deepdiff/) JSON.
Common top-level keys:

| Key | Meaning |
| --- | --- |
| `values_changed` | An attribute's value differs between the two sides. |
| `type_changes` | An attribute's type changed (e.g. `null` → `int`). |
| `dictionary_item_added` | An attribute or sub-entity exists only on side 2. |
| `dictionary_item_removed` | An attribute or sub-entity exists only on side 1. |
| `iterable_item_added` / `_removed` | Items added/removed from a list. |

Paths use bracket notation rooted at `root`:

```json
{
  "values_changed": {
    "root['TestStep']['MeaResults']['Result1']['MeaResult.Name']": {
      "new_value": "NewName",
      "old_value": "OldName"
    }
  }
}
```

### Default exclusions

The following fields are **always** excluded from diffs (regardless of
configuration):

- `*.Id`
- `*.DateCreated`
- `*.Version`

Additional exclusions can be added via `exclude_paths` / `exclude_regex_paths`
in the config or via CLI flags / API parameters.

---

## Troubleshooting

### Keyring errors

If you see `keyring.errors.NoKeyringError`, install a keyring backend:

```powershell
pip install keyrings.alt
# or on Windows, the default Windows Credential Locker is used automatically
```

### Certificate warnings

For self-signed certificates, set `verify_certificate = false` in your config
file.  The tool suppresses `urllib3` certificate warnings automatically.

### Empty diff result file

An empty diff result (`{}`) means no differences were found — this is the
expected output for exit code `0`.

### `file:` path not found

Ensure the path after `file:` is correct relative to your working directory,
or use an absolute path: `file:C:/data/baseline.json`.
