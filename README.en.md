# MySQL Skill

[中文](README.md) | [English](README.en.md)

**Let AI query MySQL without handing it your database credentials.**

Configure connections once on your machine. The local CLI reads the credentials,
connects to MySQL, and redacts the current connection's address, username, and
password from returned results. The agent invokes queries by alias without
opening the credential file or receiving credentials in chat. Works with
**Codex, Claude Code, and DeepSeek Harness (dsh)**.

## Features

- Read-only SELECT and UNION queries; CTEs on MySQL 8.0+.
- Table discovery and column inspection.
- Common read-only SQL: SHOW, DESCRIBE, system variable reads, and common query functions.
- EXPLAIN SELECT plans in traditional or JSON format; EXPLAIN ANALYZE is excluded.
- Alias listing and local diagnostics without exposing connection details.
- JSON output, credential redaction, query timeouts, and bounded results.
- Windows, macOS, and Linux; Python 3.10+ and MySQL 5.5+ required. MySQL 8.0+ recommended.

This version excludes writes, migrations, stored procedures, and MariaDB.
DDL, grants, SET, CALL, file access, and multiple statements are also rejected.
Functions remain allowlisted; unknown stored functions and UDFs are not assumed
safe. SHOW GRANTS and SHOW CREATE USER are excluded.

### MySQL Compatibility

Version strings such as `5.5.20-log`, `5.6.16-log`, and `5.7.20` are supported.
The `-log` suffix does not affect version detection.

| MySQL version | Transaction mode | Timeout |
| --- | --- | --- |
| 5.5.x, 5.6.0-5.6.4 | Regular transaction; SELECT-only grants enforce account permissions | Socket read |
| 5.6.5-5.7.7 | READ ONLY | Socket read |
| 5.7.8+ | READ ONLY | Server SELECT and socket read |

Use a dedicated SELECT-only account on every version. Socket timeout does not
cancel server work. SQL must match the target version: CTEs and window functions
require MySQL 8.0+; JSON functions require 5.7+.

## Installation

Install with the [skills CLI](https://github.com/vercel-labs/skills), which requires Node.js:

```sh
npx skills add YuiKira/mysql-skill
```

For a personal installation targeting Codex and Claude Code:

```sh
npx skills add YuiKira/mysql-skill --skill mysql-skill --agent codex claude-code --global
```

Then install the Python dependencies and configure connections as described below.
DeepSeek Harness can use the shared `~/.agents/skills/mysql-skill` directory
or a manual installation at one of the following paths.

Alternatively, download a ZIP from [Releases](https://github.com/YuiKira/mysql-skill/releases)
and extract or copy the complete repository to the skill directory for your tool:

| Tool | Personal skill path |
| --- | --- |
| Codex | `~/.agents/skills/mysql-skill` |
| Claude Code | `~/.claude/skills/mysql-skill` |
| DeepSeek Harness | `~/.dsh/skills/mysql-skill` or `~/.agents/skills/mysql-skill` |

`~` denotes your home directory. Codex and DeepSeek Harness can share the
`.agents/skills` installation. Custom DeepSeek Harness compositions need
`@deepseek-ai/dsh-skill`, `@deepseek-ai/dsh-skill-filesystem`, and
`@deepseek-ai/dsh-tool-skill`. `DSH_HOME` and `DSH_AGENTS_HOME` can override roots.

Create a virtual environment inside the skill directory and install dependencies.

Windows PowerShell:

```powershell
python -m venv .venv
& ".venv/Scripts/python.exe" -m pip install -r "requirements.txt"
& ".venv/Scripts/python.exe" "scripts/mysql_skill.py" doctor --json
```

macOS / Linux:

```sh
python3 -m venv .venv
".venv/bin/python" -m pip install -r "requirements.txt"
".venv/bin/python" "scripts/mysql_skill.py" doctor --json
```

Have the agent invoke the CLI with that environment's Python. Reload skills
or start a new session if the tool has not discovered the installation.

## Local Configuration

Manually copy `config/connections.example.json` to
`~/.mysql-skill/connections.json` and edit it locally. All values below are fictional.

```json
{
  "version": 1,
  "connections": {
    "business": {
      "host": "db.example.invalid",
      "port": 3306,
      "user": "example_reader",
      "password": "replace-locally",
      "database": "example_app"
    }
  }
}
```

Plaintext local passwords are supported. Use a dedicated SELECT-only account
and restrict file access to its local owner. Never commit the real file,
paste it into chat, or ask the agent to open it.

Override the location with `MYSQL_SKILL_CONFIG` or the global
`--config "<PATH>"` option before the subcommand. Agents discover aliases with
`config list`.

For direct network connections, add verified TLS:
`"tls": {"ca": "/local/path/ca.pem"}`. Add paired `cert` and `key` paths for
client certificates. Without `tls`, TLS is not requested. For SSH-only targets,
use the SSH skill to establish a local tunnel, then use a preconfigured MySQL alias.

The skill keeps credentials outside normal agent workflows; it does not enforce
OS file isolation. Exact configured host, username, and password strings are
redacted from output, including matching query values. Query business data only
within the user's authorized scope.

## Usage

Ask the agent, for example:

> Use the business MySQL alias to list order tables.
>
> Query the latest 10 failed orders in business; return only order ID, status, and creation time.

Replace `<PYTHON>` with the virtual environment interpreter:

```text
<PYTHON> "scripts/mysql_skill.py" config list
<PYTHON> "scripts/mysql_skill.py" schema --alias business
<PYTHON> "scripts/mysql_skill.py" schema --alias business --table orders
<PYTHON> "scripts/mysql_skill.py" query --alias business --sql "SELECT id, status FROM orders ORDER BY id DESC LIMIT 10"
<PYTHON> "scripts/mysql_skill.py" query --alias business --sql-file "query.sql" --limit 100 --timeout 15
<PYTHON> "scripts/mysql_skill.py" query --alias business --sql "SHOW TABLES"
<PYTHON> "scripts/mysql_skill.py" query --alias business --sql "DESCRIBE orders"
<PYTHON> "scripts/mysql_skill.py" query --alias business --sql "SHOW INDEX FROM orders"
<PYTHON> "scripts/mysql_skill.py" explain --alias business --sql "SELECT id FROM orders WHERE id = 42"
<PYTHON> "scripts/mysql_skill.py" explain --alias business --sql-file "query.sql" --format json
```

`query --sql "EXPLAIN SELECT ..."` is also supported. Traditional plans work
on MySQL 5.5+; JSON requires 5.6.5+. Explained SELECT limits are preserved;
`--limit` only bounds returned plan rows. SHOW/DESCRIBE do not receive an
injected SQL LIMIT, but result row and output limits still apply. JSON plans
are text cells and may be truncated; inspect `cells_truncated`. Each call
opens a fresh connection, so SHOW WARNINGS/ERRORS cannot inspect a previous call.

The default returned row limit is 100, maximum 1,000. `--timeout` defaults to
15 seconds, maximum 60. MySQL 5.7.8+ uses it for the server SELECT timeout.
On every version, socket read timeout is that value plus 5 seconds; it limits
individual read waits, not total execution time. The CLI also tightens the top-level SQL
LIMIT to the returned row limit plus one, preserving a smaller existing limit
and the offset. Scans, sorts, and aggregations can still process more rows.

The result's `execution` field reports the normalized version, read-only
transaction availability, timeout mode, and effective timeout seconds for that
mode. Raw server version banners are not returned.

Output is capped at 256 KiB and text cells at 4,096 characters. Binary cells
are size markers. Inspect `truncated` and `cells_truncated` for omitted data.
All operations except `--help` emit one JSON document. Failures exit 1, omit
raw driver diagnostics, and are never retried automatically.

See [CLI Reference](references/commands.md) for options and error codes.

## Tests

Use the interpreter with dependencies installed:

```text
<PYTHON> -m unittest discover -s tests -v
```

Default tests use fictional configurations and mocked connections. Integration
tests are skipped unless `MYSQL_SKILL_TEST_PORT` points to a disposable local
test instance. Optional `MYSQL_SKILL_TEST_PASSWORD` supplies that instance's root
password. Never target a business instance. GitHub Actions also defines
isolated MySQL 5.5, 5.6, 5.7, and 8.0 integration services.

## License

[MIT License](LICENSE).

## Tool Documentation

- [Codex Skills](https://developers.openai.com/codex/skills/)
- [Claude Code Skills](https://code.claude.com/docs/en/skills)
- [DeepSeek Harness Skill Filesystem](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md)
