import contextlib
import datetime
import decimal
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mysql_skill", ROOT / "scripts" / "mysql_skill.py")
skill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skill)


class SkillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / "connections.json"
        self.entry = {"host": "private.example.invalid", "user": "private_reader",
                      "password": "test-password-unique", "database": "example_app"}
        self.config.write_text(json.dumps({"version": 1, "connections": {"business": self.entry}}), encoding="utf-8")

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = skill.main(["--config", str(self.config), *args])
        self.assertEqual(stderr.getvalue(), "")
        document = json.loads(stdout.getvalue())
        self.assertEqual(document["schema_version"], "1.0")
        return status, document

    def test_alias_listing_does_not_connect_or_disclose_details(self):
        with patch.object(skill, "execute", side_effect=AssertionError("Unexpected connection")):
            status, result = self.invoke("config", "list")
        self.assertEqual(status, 0)
        self.assertEqual(result["data"], {"aliases": ["business"]})
        for value in self.entry.values():
            self.assertNotIn(value, json.dumps(result))

    def test_doctor_does_not_connect(self):
        with patch.object(skill, "execute", side_effect=AssertionError("Unexpected connection")):
            status, result = self.invoke("doctor", "--json")
        self.assertEqual(status, 0)
        self.assertTrue(result["data"]["ready"])
        self.assertFalse(result["data"]["network_checked"])

    def test_missing_configuration(self):
        self.config = Path(self.temp.name) / "missing.json"
        status, result = self.invoke("config", "list")
        self.assertEqual(status, 1)
        self.assertEqual(result["error"]["code"], "config_not_found")

    def test_doctor_rejects_structurally_invalid_connection_entries(self):
        self.config.write_text(json.dumps({"version": 1, "connections": {"business": None}}), encoding="utf-8")
        status, result = self.invoke("doctor")
        self.assertEqual(status, 0)
        self.assertFalse(result["data"]["ready"])
        self.assertEqual(result["data"]["invalid_aliases"], ["business"])

    def test_malformed_config_does_not_echo_values(self):
        self.config.write_text('bad secret: test-password-unique', encoding="utf-8")
        status, result = self.invoke("config", "list")
        self.assertEqual(status, 1)
        self.assertEqual(result["error"]["code"], "invalid_config")
        self.assertNotIn("test-password-unique", json.dumps(result))

    def test_unknown_alias(self):
        status, result = self.invoke("query", "--alias", "unknown", "--sql", "SELECT 1")
        self.assertEqual(status, 1)
        self.assertEqual(result["error"]["code"], "invalid_alias")

    def test_invalid_arguments_are_json(self):
        status, result = self.invoke("query", "--alias", "business", "--sql", "SELECT 1", "--limit", "secret-value")
        self.assertEqual(status, 1)
        self.assertEqual(result["error"]["code"], "invalid_arguments")
        self.assertNotIn("secret-value", json.dumps(result))

    def test_invalid_row_limit_does_not_connect(self):
        with patch.object(skill, "execute") as execute:
            status, result = self.invoke("query", "--alias", "business", "--sql", "SELECT 1", "--limit", "1001")
        self.assertEqual(status, 1)
        self.assertEqual(result["error"]["code"], "invalid_arguments")
        execute.assert_not_called()

    def test_writes_and_side_effects_are_rejected(self):
        rejected = [
            "DELETE FROM orders", "SELECT 1; SELECT 2",
            "SELECT * FROM orders FOR UPDATE", "SELECT 1 INTO OUTFILE '/tmp/file'",
            "SELECT SLEEP(1)", "SELECT GET_LOCK('x', 1)", "SELECT RELEASE_LOCK('x')",
            "SELECT LOAD_FILE('/etc/passwd')", "SELECT @x := 1", "SELECT @@hostname",
            "SELECT example_app.COUNT(*)", "SELECT arbitrary_udf(1)",
            "/*!50000 SELECT 1 */", "SELECT 1 /*!50000 INTO OUTFILE '/tmp/file' */",
            "WITH x AS (DELETE FROM orders RETURNING id) SELECT * FROM x",
        ]
        for sql in rejected:
            with self.subTest(sql=sql), self.assertRaises(skill.SkillError):
                skill.validate_sql(sql)

    def test_supported_selects_and_limits(self):
        accepted = [
            "SELECT 1;", "SELECT id FROM orders WHERE status = 'failed' ORDER BY id DESC",
            "SELECT COUNT(*), SUM(amount) FROM orders", "WITH x AS (SELECT 1 AS id) SELECT * FROM x",
            "SELECT 1 UNION ALL SELECT 2", "SELECT CASE WHEN id > 1 THEN 1 ELSE 0 END FROM orders",
            "SELECT JSON_EXTRACT(payload, '$.id') FROM orders",
            "SELECT DATE('2026-01-02'), DATE_FORMAT(created_at, '%Y-%m') FROM orders",
            "SELECT 1; -- trailing comment", "SELECT 1; /* trailing comment */",
        ]
        for sql in accepted:
            with self.subTest(sql=sql):
                self.assertIn("LIMIT 11", skill.validate_sql(sql, 10))
        self.assertIn("LIMIT 3 OFFSET 7", skill.validate_sql("SELECT id FROM orders LIMIT 3 OFFSET 7", 10))
        self.assertIn("LIMIT 11 OFFSET 7", skill.validate_sql("SELECT id FROM orders LIMIT 500 OFFSET 7", 10))
        self.assertIn("LIMIT 0", skill.validate_sql("SELECT 1 LIMIT 0", 10))

    def test_rejected_query_never_connects(self):
        with patch.object(skill, "execute") as execute:
            status, result = self.invoke("query", "--alias", "business", "--sql", "DROP TABLE orders")
        self.assertEqual(status, 1)
        self.assertEqual(result["error"]["code"], "query_rejected")
        execute.assert_not_called()

    def test_schema_uses_bound_parameters(self):
        table = "orders' OR 1=1 --"
        with patch.object(skill, "execute", return_value={}) as execute:
            status, _ = self.invoke("schema", "--alias", "business", "--table", table)
        self.assertEqual(status, 0)
        self.assertNotIn(table, execute.call_args.args[1])
        self.assertEqual(execute.call_args.args[2], ("example_app", table, 101))

    def test_output_redacts_credentials_in_values_and_columns(self):
        data = {"columns": [self.entry["password"]], "rows": [[" / ".join(self.entry.values())]]}
        with patch.object(skill, "execute", return_value=data):
            status, result = self.invoke("query", "--alias", "business", "--sql", "SELECT 1")
        self.assertEqual(status, 0)
        for key in ("host", "user", "password"):
            self.assertNotIn(self.entry[key], json.dumps(result))
        self.assertIn("[redacted]", json.dumps(result))

    def test_raw_exceptions_and_warnings_are_suppressed(self):
        import warnings

        def failing(*args):
            warnings.warn(self.entry["password"])
            raise RuntimeError(str(self.entry))

        with patch.object(skill, "execute", side_effect=failing):
            status, result = self.invoke("query", "--alias", "business", "--sql", "SELECT 1")
        self.assertEqual(status, 1)
        self.assertEqual(result["error"]["code"], "internal_error")
        self.assertNotIn(self.entry["password"], json.dumps(result))

    def test_short_secret_does_not_corrupt_result_envelope(self):
        self.entry["password"] = "1"
        self.config.write_text(json.dumps({"version": 1, "connections": {"business": self.entry}}), encoding="utf-8")
        with patch.object(skill, "execute", return_value={"rows": [["1"]], "row_count": 1}):
            _, result = self.invoke("query", "--alias", "business", "--sql", "SELECT 1")
        self.assertEqual(result["data"]["rows"], [["[redacted]"]])

    def test_execute_sets_timeout_readonly_and_bounds_fetch(self):
        import pymysql
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.description = [("id",)]
        cursor.fetchmany.return_value = [(1,), (2,), (3,)]
        with patch.object(pymysql, "connect", return_value=connection):
            result = skill.execute({}, "SELECT id FROM orders LIMIT 3", None, 2, 15)
        calls = cursor.execute.call_args_list
        self.assertEqual(calls[0].args, ("SET SESSION MAX_EXECUTION_TIME = %s", (15000,)))
        self.assertEqual(calls[1].args, ("START TRANSACTION READ ONLY",))
        cursor.fetchmany.assert_called_once_with(3)
        self.assertEqual(result["rows"], [[1], [2]])
        self.assertTrue(result["truncated"])
        connection.close.assert_called_once()

    def test_setup_failure_stops_before_user_query_and_closes(self):
        import pymysql
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = pymysql.OperationalError(1045, self.entry["password"])
        with patch.object(pymysql, "connect", return_value=connection):
            with self.assertRaises(skill.SkillError) as caught:
                skill.execute({}, "SELECT 1 LIMIT 2", None, 1, 15)
        self.assertEqual(caught.exception.code, "access_denied")
        self.assertEqual(cursor.execute.call_count, 1)
        connection.close.assert_called_once()

    def test_connection_loss_is_not_retryable(self):
        import pymysql
        with patch.object(pymysql, "connect", side_effect=pymysql.OperationalError(2013, self.entry["password"])) as connect:
            status, result = self.invoke("query", "--alias", "business", "--sql", "SELECT 1")
        self.assertEqual(status, 1)
        self.assertEqual(result["error"]["code"], "connection_lost")
        self.assertFalse(result["error"]["retryable"])
        connect.assert_called_once()

    def test_tls_requires_verified_ca_and_paired_client_keys(self):
        self.entry["tls"] = {"ca": "/fake/ca.pem"}
        options = skill.connection_options({"business": self.entry}, "business", 15)
        self.assertTrue(options["ssl_verify_cert"])
        self.assertTrue(options["ssl_verify_identity"])
        self.assertFalse(options["local_infile"])
        self.entry["tls"]["cert"] = "/fake/client.pem"
        with self.assertRaises(skill.SkillError):
            skill.connection_options({"business": self.entry}, "business", 15)

    def test_output_byte_limit_preserves_valid_json_and_signals_truncation(self):
        data = {"columns": ["value"], "rows": [["\u4e2d" * 4096] for _ in range(100)],
                "row_count": 100, "truncated": False, "cells_truncated": False}
        result = skill.bound_output({"success": True, "data": data})
        self.assertLessEqual(len(skill.encode_result(result).encode("utf-8")), skill.MAX_OUTPUT_BYTES)
        self.assertTrue(result["data"]["truncated"])
        self.assertEqual(result["data"]["row_count"], len(result["data"]["rows"]))

    def test_cell_types(self):
        self.assertEqual(skill.cell(decimal.Decimal("1.20")), ("1.20", False))
        self.assertEqual(skill.cell(datetime.date(2026, 1, 2)), ("2026-01-02", False))
        self.assertEqual(skill.cell(b"secret"), ("[binary: 6 bytes]", True))
        self.assertTrue(skill.cell("x" * 5000)[1])
        self.assertEqual(len(skill.cell("x" * 5000)[0]), skill.MAX_CELL_CHARS)

    def test_redaction_precedes_cell_truncation(self):
        secret = "unique-password-at-boundary"
        value, truncated = skill.cell("x" * 4090 + secret, [secret])
        self.assertTrue(truncated)
        self.assertNotIn("unique", value)

    def test_cli_subprocess_contract(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "mysql_skill.py"),
                                 "--config", str(self.config), "config", "list"],
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stderr, "")
        self.assertEqual(json.loads(result.stdout)["data"], {"aliases": ["business"]})


if __name__ == "__main__":
    unittest.main()
