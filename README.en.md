# MySQL Skill

[中文](README.md) | [English](README.en.md)

Query MySQL through local aliases with **Codex, Claude Code, and DeepSeek Harness (dsh)**.
The Python CLI reads connection addresses, usernames, and plaintext passwords
internally from a local file. The agent uses aliases without opening that file.

## Features

- Read-only SELECT queries, including CTEs and UNION.
- Table discovery and column inspection.
- Alias listing and local diagnostics without exposing connection details.
- JSON output, credential redaction, query timeouts, and bounded results.
- Windows, macOS, and Linux; Python 3.10+ and MySQL 5.7+ required. MySQL 8.0+ recommended.

This version excludes writes, migrations, stored procedures, and MariaDB.

## Installation

Clone or copy the complete repository to the skill directory for your tool:

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
```

The default returned row limit is 100, maximum 1,000. The server SELECT timeout
defaults to 15 seconds, maximum 60. The CLI also tightens the top-level SQL
LIMIT to the returned row limit plus one, preserving a smaller existing limit
and the offset. Scans, sorts, and aggregations can still process more rows.

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
password. Never target a business instance. GitHub Actions also defines an
isolated MySQL 8.0 integration service.

## License

[MIT License](LICENSE).

## Tool Documentation

- [Codex Skills](https://developers.openai.com/codex/skills/)
- [Claude Code Skills](https://code.claude.com/docs/en/skills)
- [DeepSeek Harness Skill Filesystem](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md)
