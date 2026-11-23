# CLI Reference

All operations emit JSON except `--help`. All paths belong to the local machine.

```text
python "<ROOT>/scripts/mysql_skill.py" [--config "<PATH>"] <command> [options]
```

`--config` must precede the command. Resolution order: explicit option,
`MYSQL_SKILL_CONFIG`, then `~/.mysql-skill/connections.json`.

| Command | Options | Result |
| --- | --- | --- |
| `config list` | None | Alias names only; no connection |
| `doctor` | `--json` (optional) | Version, dependencies, config presence, aliases, invalid aliases, local readiness; no connection |
| `query` | `--alias NAME`, one of `--sql SQL` / `--sql-file PATH` | One read-only SELECT, SHOW, DESCRIBE, or EXPLAIN SELECT result |
| `explain` | `--alias NAME`, one of `--sql SQL` / `--sql-file PATH`, optional `--format traditional|json` | Execution plan for the supplied SELECT |
| `schema` | `--alias NAME`, optional `--table NAME` | Tables, or columns of one table |

`query`, `explain`, and `schema` accept optional `--via SSH_ALIAS`,
`--limit 1..1000` (default 100), and
`--timeout 1..60` seconds (default 15). SQL text and files are limited to 64 KiB.
Only one statement is supported. Common built-in functions are supported;
unknown or qualified functions, user-variable assignments, writes, locks, executable
comments, and file output are rejected. SELECT UNION is supported. CTEs and
window functions require MySQL 8.0+; JSON functions require 5.7+.

Supported SHOW families: DATABASES, TABLES, COLUMNS, INDEX, CREATE DATABASE,
CREATE TABLE, CREATE VIEW, TABLE STATUS, VARIABLES, STATUS, WARNINGS, ERRORS,
PROCESSLIST, ENGINES, COLLATION, and CHARACTER SET. Parsed LIKE/WHERE filters
and FULL/GLOBAL/SESSION options are supported where MySQL accepts them.
DESCRIBE/DESC accepts a table. System variables can be read with `@@`.

The function allowlist includes common string, numeric, date, JSON, aggregate,
window, and connection-information builtins. Unknown functions remain rejected;
custom stored functions and UDFs are not inferred to be read-only. DDL, DML,
SET, USE, CALL, GRANT, administrative mutations, file access, and multiple
statements are rejected. SHOW GRANTS and CREATE USER are excluded.

EXPLAIN accepts SELECT or UNION only, in traditional (MySQL 5.5+) or JSON
(MySQL 5.6.5+) format. EXPLAIN ANALYZE, EXTENDED, TREE, write-statement plans,
and FOR CONNECTION are excluded. The `explain` command takes an unprefixed
SELECT; the `query` command also accepts a complete EXPLAIN SELECT.

SELECT LIMIT is left unchanged for execution plans. `--limit` bounds returned
plan and metadata rows without rewriting the SQL. JSON plans are returned as a
string cell under the usual result envelope and remain subject to cell and
output truncation. SHOW WARNINGS/ERRORS cannot inspect a prior CLI call because
each invocation opens a new connection.

Queries use a streaming cursor and close the
connection after collecting at most limit + 1 rows. The top-level SQL LIMIT is
capped at limit + 1, preserving smaller limits and offsets. No automatic retries occur.
Session setup uses the numeric version from the MySQL handshake. Suffixes such
as `-log` and `-commercial` are accepted. Raw version banners are not returned.

| MySQL version | Transaction | Timeout |
| --- | --- | --- |
| 5.5.x, 5.6.0-5.6.4 | Regular transaction; SELECT-only account required | Socket read only |
| 5.6.5-5.7.7 | READ ONLY | Socket read only |
| 5.7.8+ | READ ONLY | Server MAX_EXECUTION_TIME and socket read |

`--timeout` controls the server timeout where available; the socket read
timeout is always `--timeout + 5` seconds. Socket timeout does not cancel the
server query and is not an end-to-end deadline. No query is retried automatically.
Unexpected setup errors stop the query rather than switching execution modes.
Results include an `execution` object with `server_version`,
`read_only_transaction`, `timeout_mode` (`server` or `socket`), and
`timeout_seconds` for that mode. A SELECT-only account is required on all versions;
MySQL 5.5 has no READ ONLY transaction mode. Server versions below 5.5 and MariaDB
are rejected before session SQL is sent.

## Local Configuration

The example contains fictional values. Keep actual files outside the repository.
The agent must not open the real file. Configure it manually in a local editor.

```json
{
  "version": 1,
  "connections": {
    "example": {
      "host": "db.example.invalid",
      "port": 3306,
      "user": "example_reader",
      "password": "replace-locally",
      "database": "example_app",
      "tls": {"ca": "/local/path/ca.pem"}
    }
  }
}
```

`port` defaults to 3306. `tls` is optional; when present, `ca` is required and
certificate and hostname verification are enabled. Optional client `cert` and
`key` paths must be supplied together. Without `tls`, no TLS is requested.
Use verified TLS for direct network connections, or an authorized SSH tunnel.

## SSH Access

Use the existing database alias and an installed SSH skill v4 alias:

```text
<PYTHON> "<ROOT>/scripts/mysql_skill.py" query --alias business --via jump --sql "SELECT 1"
<PYTHON> "<ROOT>/scripts/mysql_skill.py" schema --alias business --via jump --table orders
<PYTHON> "<ROOT>/scripts/mysql_skill.py" explain --alias business --via jump --sql "SELECT id FROM orders WHERE id = 42"
```

The configured database host and port are resolved from the SSH server. The CLI
passes that destination to SSH skill internally, captures its output, and connects
through its allocated `127.0.0.1` port. Database credentials and SQL are never
passed to SSH processes. Destination addresses are present in internal tunnel
process arguments, but are not returned to the agent. The database configuration
is unchanged. TLS continues to verify the original database hostname.

SSH skill is discovered beside the loaded MySQL skill, then under personal
`.agents`, `.codex`, `.claude`, and `.dsh` skill directories. Set
`MYSQL_SKILL_SSH_ROOT` to override discovery. Set `MYSQL_SKILL_SSH_PYTHON` if SSH
uses a separate interpreter; otherwise its own `.venv` is preferred, followed
by the current interpreter's base Python. Install SSH dependencies in that
interpreter, independently of the MySQL environment.

Each call creates and stops its own tunnel, including after query errors. Existing
tunnels are not reused or stopped. Cleanup failure is reported in `meta.warnings`
with the tunnel ID; the query result or original error is retained. Inspect or stop
that ID with SSH skill before repeating the operation. SSH subprocesses have a
separate 45-second timeout; `--timeout` still controls database waits only.
On `ssh_tunnel_unknown`, inspect SSH tunnel state before retrying because startup
or shutdown may have completed. No direct or remote SQL fallback occurs.

Use a SELECT-only MySQL account. Restrict local file permissions to its owner.
The skill prevents normal agent workflows from reading credentials; it does
not enforce OS access isolation against an agent that can read arbitrary files.

## Result Example

```json
{
  "schema_version": "1.0",
  "success": true,
  "operation": "query",
  "data": {
    "columns": ["id"],
    "rows": [[42]],
    "row_count": 1,
    "truncated": false,
    "cells_truncated": false
  },
  "error": null,
  "meta": {"request_id": "example-request-id", "elapsed_ms": 12}
}
```

Cells longer than 4,096 characters are cut; binary cells are returned as size
markers. Exact configured host, user, and password strings are replaced with
`[redacted]`, including matches in query results. This can alter business values.
Do not query credentials or connection metadata to test this against real data.

Error codes include `invalid_arguments`, `invalid_alias`, `config_not_found`,
`invalid_config`, `invalid_sql`, `query_rejected`, `sql_file_error`,
`dependency_missing`, `access_denied`, `query_timeout`, `connection_failed`,
`connection_lost`, `unsupported_server`, `unsupported_feature`, `database_error`, `output_too_large`, `interrupted`, and
`internal_error`, `ssh_skill_missing`, `ssh_unavailable`, `ssh_tunnel_failed`, and
`ssh_tunnel_unknown`. All errors have `retryable=false`. Raw server messages,
SQL text, stack traces, and connection arguments are not returned.
