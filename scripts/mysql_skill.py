#!/usr/bin/env python3
"""Query MySQL through local connection aliases."""

from __future__ import annotations

import argparse
import datetime as dt
import decimal
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
import uuid
import warnings

VERSION = "0.1.0"
MAX_OUTPUT_BYTES = 256 * 1024
MAX_SQL_BYTES = 64 * 1024
MAX_CELL_CHARS = 4096
DEFAULT_CONFIG = Path.home() / ".mysql-skill" / "connections.json"
SAFE_FUNCTIONS = frozenset("""ABS ACOS ADDDATE ADDTIME ANY_VALUE ARRAY_AGG ASCII ASIN ATAN ATAN2 AVG
BIT_AND BIT_COUNT BIT_LENGTH BIT_OR BIT_XOR CAST CEIL CEILING CHAR_LENGTH
CASE CHARACTER_LENGTH COALESCE CONCAT CONCAT_WS CONVERT COS COT COUNT CRC32
CURDATE CURRENT_DATE CURRENT_TIME CURRENT_TIMESTAMP CURTIME DATE DATE_ADD
DATE_DIFF DATE_FORMAT DATE_SUB DATE_TRUNC DATEDIFF DAY DAYNAME DAYOFMONTH
DAYOFWEEK DAYOFYEAR DENSE_RANK ELT EXP EXTRACT FIELD FIND_IN_SET FIRST_VALUE
FLOOR FROM_DAYS FROM_UNIXTIME GREATEST GROUP_CONCAT HEX HOUR IF IFNULL
INSTR ISNULL JSON_ARRAY JSON_ARRAYAGG JSON_CONTAINS JSON_CONTAINS_PATH
JSON_EXTRACT JSON_KEYS JSON_LENGTH JSON_OBJECT JSON_OBJECTAGG JSON_QUOTE
JSON_TYPE JSON_UNQUOTE JSON_VALID LAG LAST_DAY LAST_VALUE LEAD LEAST LEFT
LENGTH LN LOCATE LOG LOG10 LOG2 LOWER LPAD LTRIM MAX MD5 MICROSECOND MIN
MINUTE MOD MONTH MONTHNAME NOW NTH_VALUE NTILE NULLIF OCT OCTET_LENGTH
ORD PERCENT_RANK PI POSITION POW POWER QUARTER RADIANS RAND RANK REPEAT
REPLACE REVERSE RIGHT ROUND ROW_NUMBER RPAD RTRIM SECOND SHA SHA1 SHA2
SIGN SIN SPACE SQRT STD STDDEV STDDEV_POP STDDEV_SAMP STR_TO_DATE STRCMP
SUBDATE SUBSTR SUBSTRING SUBSTRING_INDEX SUM TAN TIME TIMEDIFF TIMESTAMP
TIMESTAMPADD TIMESTAMPDIFF TIME_FORMAT TIME_TO_SEC TIME_TO_STR TO_DAYS TRIM TRUNCATE
TS_OR_DS_TO_DATE TS_OR_DS_TO_TIMESTAMP
UCASE UNHEX UNIX_TIMESTAMP UPPER VARIANCE VAR_POP VAR_SAMP WEEK WEEKDAY
WEEKOFYEAR YEAR YEARWEEK
""".split())


class SkillError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class JsonParser(argparse.ArgumentParser):
    def error(self, message):
        raise SkillError("invalid_arguments", "Invalid arguments; use --help for syntax.")


def parser():
    root = JsonParser(description=__doc__)
    root.add_argument("--config", type=Path, help="Local connection file path")
    commands = root.add_subparsers(dest="command", required=True)
    config = commands.add_parser("config", help="Inspect aliases without connection details")
    config.add_subparsers(dest="config_command", required=True).add_parser("list")
    doctor = commands.add_parser("doctor", help="Inspect local readiness without connecting")
    doctor.add_argument("--json", action="store_true", help="JSON is always enabled")
    for name in ("query", "schema"):
        command = commands.add_parser(name)
        command.add_argument("--alias", required=True)
        command.add_argument("--limit", type=int, default=100)
        command.add_argument("--timeout", type=int, default=15)
        if name == "query":
            sql = command.add_mutually_exclusive_group(required=True)
            sql.add_argument("--sql")
            sql.add_argument("--sql-file", type=Path)
        else:
            command.add_argument("--table")
    return root


def config_path(args):
    return args.config or Path(os.environ.get("MYSQL_SKILL_CONFIG", DEFAULT_CONFIG))


def load_config(path):
    try:
        if path.stat().st_size > 1024 * 1024:
            raise SkillError("invalid_config", "Connection file exceeds 1 MiB.")
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise SkillError("config_not_found", "Create the local connection file from the example.") from None
    except (OSError, UnicodeError, ValueError):
        raise SkillError("invalid_config", "Cannot read a valid connection file.") from None
    if (not isinstance(document, dict) or document.get("version") != 1
            or not isinstance(document.get("connections"), dict)):
        raise SkillError("invalid_config", "Expected version 1 and a connections object.")
    connections = document["connections"]
    if any(not re.fullmatch(r"[\w.-]{1,64}", alias) for alias in connections):
        raise SkillError("invalid_config", "Aliases must use letters, digits, dots, underscores, or hyphens.")
    return connections


def connection_options(connections, alias, timeout):
    if alias not in connections:
        raise SkillError("invalid_alias", "Unknown alias; run config list.")
    item = connections[alias]
    if not isinstance(item, dict):
        raise SkillError("invalid_config", "Invalid connection entry.")
    required = ("host", "user", "password", "database")
    allowed = {*required, "port", "tls"}
    if (set(item) - allowed or any(not isinstance(item.get(key), str) for key in required)
            or any(not item[key] for key in ("host", "user", "database"))):
        raise SkillError("invalid_config", "Expected host, user, password, database, and optional port or tls.")
    port = item.get("port", 3306)
    if type(port) is not int or not 1 <= port <= 65535:
        raise SkillError("invalid_config", "Port must be an integer from 1 to 65535.")
    options = {key: item[key] for key in required}
    options.update(port=port, charset="utf8mb4", connect_timeout=min(timeout, 10),
                   read_timeout=timeout + 5, write_timeout=timeout,
                   autocommit=False, local_infile=False)
    tls = item.get("tls")
    if tls is not None:
        if (not isinstance(tls, dict) or set(tls) - {"ca", "cert", "key"}
                or not isinstance(tls.get("ca"), str) or not tls["ca"]
                or bool(tls.get("cert")) != bool(tls.get("key"))
                or any(not isinstance(value, str) or not value for value in tls.values())):
            raise SkillError("invalid_config", "TLS requires a CA path and optional paired cert and key paths.")
        options.update(ssl_ca=tls["ca"], ssl_verify_cert=True, ssl_verify_identity=True)
        if "cert" in tls:
            options.update(ssl_cert=tls["cert"], ssl_key=tls["key"])
    return options


def validate_sql(sql, row_limit=None):
    if not sql.strip() or len(sql.encode("utf-8")) > MAX_SQL_BYTES:
        raise SkillError("invalid_sql", "Provide a query no larger than 64 KiB.")
    if "/*!" in sql or "/*M!" in sql.upper():
        raise SkillError("query_rejected", "Executable SQL comments are not supported.")
    import sqlglot
    from sqlglot import exp

    # Parser diagnostics may contain query literals.
    logging.getLogger("sqlglot").disabled = True
    try:
        statements = sqlglot.parse(sql, read="mysql", error_level=sqlglot.ErrorLevel.RAISE)
        statements = [item for item in statements if item is not None and not isinstance(item, exp.Semicolon)]
    except Exception:
        raise SkillError("invalid_sql", "Cannot parse the query as MySQL SQL.") from None
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
        raise SkillError("query_rejected", "Only one SELECT or SELECT UNION statement is supported.")
    for node in statements[0].walk():
        if isinstance(node, (exp.Into, exp.Lock, exp.Command, exp.DDL, exp.DML,
                             exp.Parameter, exp.SessionParameter)):
            raise SkillError("query_rejected", "Writes, locks, variables, and output files are not supported.")
        if isinstance(node, exp.Func):
            name = node.name.upper() if isinstance(node, exp.Anonymous) else node.sql_name()
            if name not in SAFE_FUNCTIONS:
                raise SkillError("query_rejected", "The query contains an unsupported function.")
            if isinstance(node.parent, exp.Dot):
                raise SkillError("query_rejected", "Qualified function calls are not supported.")
    tree = statements[0]
    if row_limit is not None:
        existing = tree.args.get("limit")
        expression = existing.expression if existing else None
        cap = row_limit + 1
        if isinstance(expression, exp.Literal) and expression.is_int:
            cap = min(cap, max(0, int(expression.this)))
        tree.limit(cap, copy=False)
    return tree.sql(dialect="mysql")


def dependency_status():
    return {name: importlib.util.find_spec(name) is not None for name in ("pymysql", "sqlglot")}


def require_dependencies():
    if not all(dependency_status().values()):
        raise SkillError("dependency_missing", "Install requirements.txt with the Python interpreter used for this CLI.")


def cell(value, secrets=()):
    truncated = False
    if isinstance(value, bytes):
        return f"[binary: {len(value)} bytes]", True
    if isinstance(value, (dt.date, dt.time, dt.datetime)):
        value = value.isoformat()
    elif isinstance(value, (decimal.Decimal, dt.timedelta)):
        value = str(value)
    value = redact(value, secrets)
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        marker = "[truncated]"
        value = value[:MAX_CELL_CHARS - len(marker)] + marker
        truncated = True
    return value, truncated


def database_error(error):
    code = error.args[0] if error.args and isinstance(error.args[0], int) else None
    if code in (1044, 1045, 1142, 1143, 1227):
        return SkillError("access_denied", "Authentication or query permission was denied.")
    if code in (1205, 1317, 1969, 3024):
        return SkillError("query_timeout", "The server cancelled or timed out the query.")
    if code in (2002, 2003, 2005):
        return SkillError("connection_failed", "Cannot establish a database connection.")
    if code in (2006, 2013):
        return SkillError("connection_lost", "Connection ended; the server may still be processing the query. Do not retry automatically.")
    return SkillError("database_error", "Database operation failed; raw diagnostics are suppressed.")


def execute(options, sql, params, limit, timeout):
    import pymysql

    connection = None
    try:
        connection = pymysql.connect(**options, cursorclass=pymysql.cursors.SSCursor)
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION MAX_EXECUTION_TIME = %s", (timeout * 1000,))
            cursor.execute("START TRANSACTION READ ONLY")
            cursor.execute(sql, params)
            columns = [column[0] for column in cursor.description or ()]
            rows = []
            truncated_cells = False
            for raw_row in cursor.fetchmany(limit + 1):
                secrets = [options.get(key) for key in ("host", "user", "password") if options.get(key)]
                converted = [cell(value, secrets) for value in raw_row]
                rows.append([value for value, _ in converted])
                truncated_cells |= any(cut for _, cut in converted)
            truncated = len(rows) > limit
            return {"columns": columns, "rows": rows[:limit], "row_count": min(len(rows), limit),
                    "truncated": truncated, "cells_truncated": truncated_cells}
    except pymysql.MySQLError as error:
        raise database_error(error) from None
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def run(args, secrets):
    path = config_path(args)
    if args.command == "doctor":
        dependencies = dependency_status()
        connections = load_config(path) if path.exists() else {}
        aliases = sorted(connections)
        invalid_aliases = []
        for alias in aliases:
            try:
                connection_options(connections, alias, 15)
            except SkillError:
                invalid_aliases.append(alias)
        return {"version": VERSION, "python_supported": sys.version_info >= (3, 10),
                "dependencies": dependencies, "config_exists": path.exists(), "aliases": aliases,
                "invalid_aliases": invalid_aliases,
                "ready": all(dependencies.values()) and bool(aliases) and not invalid_aliases,
                "network_checked": False}
    connections = load_config(path)
    if args.command == "config":
        return {"aliases": sorted(connections)}
    if not 1 <= args.limit <= 1000 or not 1 <= args.timeout <= 60:
        raise SkillError("invalid_arguments", "Limit must be 1..1000 and timeout must be 1..60 seconds.")
    options = connection_options(connections, args.alias, args.timeout)
    secrets.extend(options[key] for key in ("host", "user", "password") if options[key])
    require_dependencies()
    params = None
    if args.command == "query":
        try:
            if args.sql_file:
                if args.sql_file.stat().st_size > MAX_SQL_BYTES:
                    raise SkillError("invalid_sql", "SQL file exceeds 64 KiB.")
                sql = args.sql_file.read_text(encoding="utf-8-sig")
            else:
                sql = args.sql
        except (OSError, UnicodeError):
            raise SkillError("sql_file_error", "Cannot read the SQL file.") from None
        sql = validate_sql(sql, args.limit)
    elif args.table:
        sql = ("SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, COLUMN_KEY, EXTRA "
               "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
               "ORDER BY ORDINAL_POSITION LIMIT %s")
        params = (options["database"], args.table, args.limit + 1)
    else:
        sql = ("SELECT TABLE_NAME, TABLE_TYPE FROM information_schema.TABLES "
               "WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME LIMIT %s")
        params = (options["database"], args.limit + 1)
    return execute(options, sql, params, args.limit, args.timeout)


def redact(value, secrets):
    if isinstance(value, str):
        for secret in sorted(set(secrets), key=len, reverse=True):
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: redact(item, secrets) for key, item in value.items()}
    return value


def encode_result(result):
    return json.dumps(result, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def bound_output(result):
    data = result.get("data")
    if isinstance(data, dict) and "rows" in data:
        while len(encode_result(result).encode("utf-8")) > MAX_OUTPUT_BYTES and data["rows"]:
            data["rows"].pop()
            data["row_count"] = len(data["rows"])
            data["truncated"] = True
    if len(encode_result(result).encode("utf-8")) > MAX_OUTPUT_BYTES:
        result.update(success=False, data=None,
                      error={"code": "output_too_large", "message": "Result metadata exceeds the output limit.",
                             "retryable": False})
    return result


def main(argv=None):
    started = time.monotonic()
    secrets = []
    result = {"schema_version": "1.0", "success": False, "operation": "unknown", "data": None,
              "error": None, "meta": {"request_id": str(uuid.uuid4()), "elapsed_ms": 0}}
    try:
        args = parser().parse_args(argv)
        result["operation"] = "config.list" if args.command == "config" else args.command
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result["data"] = run(args, secrets)
        result["success"] = True
    except SkillError as error:
        result["error"] = {"code": error.code, "message": str(error), "retryable": False}
    except KeyboardInterrupt:
        result["error"] = {"code": "interrupted", "message": "Operation interrupted. Do not retry automatically.", "retryable": False}
    except Exception:
        result["error"] = {"code": "internal_error", "message": "Operation failed; raw diagnostics are suppressed.", "retryable": False}
    result["meta"]["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    result["data"] = redact(result["data"], secrets)
    result = bound_output(result)
    print(encode_result(result))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
