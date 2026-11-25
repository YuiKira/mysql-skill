"""Run only against an explicitly configured disposable test server."""

import json
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("MYSQL_SKILL_TEST_PORT"), "No disposable MySQL test server configured")
class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / "connections.json"
        self.entry = {"host": "127.0.0.1", "port": int(os.environ["MYSQL_SKILL_TEST_PORT"]),
                      "user": "root", "password": os.environ.get("MYSQL_SKILL_TEST_PASSWORD", ""),
                      "database": "information_schema"}
        self.write_config()

    def write_config(self):
        self.config.write_text(json.dumps({"version": 1, "connections": {"disposable": self.entry}}), encoding="utf-8")

    def invoke(self, command, *args):
        process = subprocess.run([sys.executable, str(ROOT / "scripts" / "mysql_skill.py"),
                                  "--config", str(self.config), command,
                                  "--alias", "disposable", *args],
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(process.stderr, "")
        result = json.loads(process.stdout)
        self.assertEqual(process.returncode, 0 if result["success"] else 1)
        return result

    @contextmanager
    def writable_database(self):
        import pymysql

        database = "mysql_skill_test_" + uuid.uuid4().hex
        with pymysql.connect(**self.entry, autocommit=True) as admin:
            with admin.cursor() as cursor:
                cursor.execute(f"CREATE DATABASE `{database}`")
                try:
                    cursor.execute(f"CREATE TABLE `{database}`.items (id INT PRIMARY KEY AUTO_INCREMENT, "
                                   "name VARCHAR(80) NOT NULL UNIQUE, amount INT NOT NULL) ENGINE=InnoDB")
                    self.entry["database"] = database
                    self.write_config()
                    yield cursor
                finally:
                    cursor.execute(f"DROP DATABASE `{database}`")

    def test_crud_commits_across_independent_calls(self):
        with self.writable_database():
            inserted = self.invoke("query", "--sql", "INSERT INTO items(name,amount) VALUES ('one',1),('two',2)", "--limit", "1")
            self.assertTrue(inserted["success"], inserted["error"])
            self.assertEqual(inserted["data"]["affected_rows"], 2)
            self.assertEqual(inserted["data"]["last_insert_id"], 1)
            self.assertTrue(inserted["data"]["committed"])
            self.assertFalse(inserted["data"]["execution"]["read_only_transaction"])
            self.assertEqual(inserted["data"]["execution"]["timeout_mode"], "socket")
            updated = self.invoke("query", "--sql", "UPDATE items SET amount=7 WHERE name='one'")
            self.assertTrue(updated["success"], updated["error"])
            self.assertEqual(updated["data"]["affected_rows"], 1)
            self.assertIsNone(updated["data"]["last_insert_id"])
            rows = self.invoke("query", "--sql", "SELECT name,amount FROM items ORDER BY id")
            self.assertEqual(rows["data"]["rows"], [["one", 7], ["two", 2]])
            deleted = self.invoke("query", "--sql", "DELETE FROM items WHERE name='two'")
            self.assertTrue(deleted["success"], deleted["error"])
            self.assertEqual(deleted["data"]["affected_rows"], 1)
            missing = self.invoke("query", "--sql", "DELETE FROM items WHERE id=999")
            self.assertTrue(missing["data"]["committed"])
            self.assertEqual(missing["data"]["affected_rows"], 0)
            self.assertEqual(self.invoke("query", "--sql", "SELECT COUNT(*) FROM items")["data"]["rows"], [[1]])

    def test_insert_select_ignore_upsert_and_sql_file(self):
        with self.writable_database():
            sql_file = Path(self.temp.name) / "insert.sql"
            sql_file.write_text("INSERT INTO items(name,amount) VALUES ('one',1)", encoding="utf-8")
            self.assertTrue(self.invoke("query", "--sql-file", str(sql_file))["success"])
            statements = [
                "INSERT INTO items(name,amount) SELECT 'two',amount FROM items WHERE name='one'",
                "INSERT IGNORE INTO items(name,amount) VALUES ('one',99)",
                "INSERT INTO items(name,amount) VALUES ('one',3) ON DUPLICATE KEY UPDATE amount=VALUES(amount)",
            ]
            for sql in statements:
                result = self.invoke("query", "--sql", sql)
                self.assertTrue(result["success"], result["error"])
                self.assertTrue(result["data"]["committed"])
            self.assertEqual(self.invoke("query", "--sql", "SELECT name,amount FROM items ORDER BY name")["data"]["rows"],
                             [["one", 3], ["two", 1]])

    def test_failed_multirow_insert_rolls_back(self):
        with self.writable_database():
            failed = self.invoke("query", "--sql", "INSERT INTO items(name,amount) VALUES ('same',1),('same',2)")
            self.assertFalse(failed["success"])
            self.assertEqual(failed["error"]["code"], "database_error")
            self.assertFalse(failed["error"]["retryable"])
            self.assertEqual(self.invoke("query", "--sql", "SELECT COUNT(*) FROM items")["data"]["rows"], [[0]])

    def test_existing_select_only_account_cannot_write(self):
        with self.writable_database() as cursor:
            username = "reader_" + uuid.uuid4().hex[:8]
            cursor.execute(f"CREATE USER '{username}'@'%' IDENTIFIED BY 'disposable-reader-password'")
            try:
                cursor.execute(f"GRANT SELECT ON `{self.entry['database']}`.* TO '{username}'@'%'")
                self.entry.update(user=username, password="disposable-reader-password")
                self.write_config()
                self.assertTrue(self.invoke("query", "--sql", "SELECT COUNT(*) FROM items")["success"])
                failed = self.invoke("query", "--sql", "INSERT INTO items(name,amount) VALUES ('blocked',1)")
                self.assertFalse(failed["success"])
                self.assertEqual(failed["error"]["code"], "access_denied")
                for value in (username, self.entry["password"]):
                    self.assertNotIn(value, json.dumps(failed))
                self.assertEqual(self.invoke("query", "--sql", "SELECT COUNT(*) FROM items")["data"]["rows"], [[0]])
            finally:
                cursor.execute(f"DROP USER '{username}'@'%'")

    def test_select_and_streaming_truncation(self):
        result = self.invoke("query", "--sql", "SELECT 1 AS n UNION ALL SELECT 2 UNION ALL SELECT 3", "--limit", "2")
        self.assertTrue(result["success"], result["error"])
        self.assertEqual(result["data"]["rows"], [[1], [2]])
        self.assertTrue(result["data"]["truncated"])
        execution = result["data"]["execution"]
        version = tuple(int(part) for part in execution["server_version"].split("."))
        self.assertEqual(execution["read_only_transaction"], version >= (5, 6, 5))
        self.assertEqual(execution["timeout_mode"], "server" if version >= (5, 7, 8) else "socket")

    def test_existing_limit_and_offset(self):
        result = self.invoke("query", "--sql", "SELECT 1 AS n UNION ALL SELECT 2 UNION ALL SELECT 3 LIMIT 1 OFFSET 1")
        self.assertTrue(result["success"], result["error"])
        self.assertEqual(result["data"]["rows"], [[2]])
        self.assertFalse(result["data"]["truncated"])

    def test_schema_tables_and_columns(self):
        tables = self.invoke("schema", "--limit", "1")
        self.assertTrue(tables["success"], tables["error"])
        self.assertEqual(tables["data"]["row_count"], 1)
        self.assertTrue(tables["data"]["truncated"])
        columns = self.invoke("schema", "--table", "TABLES")
        self.assertTrue(columns["success"], columns["error"])
        self.assertIn("TABLE_NAME", [row[0] for row in columns["data"]["rows"]])

    def test_decimal_date_binary_and_text_truncation(self):
        result = self.invoke("query", "--sql",
                             "SELECT CAST(1.25 AS DECIMAL(4,2)), DATE('2026-01-02'), CAST('abc' AS BINARY), REPEAT('x', 5000)")
        self.assertTrue(result["success"], result["error"])
        row = result["data"]["rows"][0]
        self.assertEqual(row[:3], ["1.25", "2026-01-02", "[binary: 3 bytes]"])
        self.assertTrue(result["data"]["cells_truncated"])

    def test_explain_traditional_and_query_entrypoint(self):
        for command, sql in (("explain", "SELECT 1"), ("query", "EXPLAIN SELECT 1")):
            with self.subTest(command=command):
                result = self.invoke(command, "--sql", sql)
                self.assertTrue(result["success"], result["error"])
                self.assertIn("select_type", result["data"]["columns"])
                self.assertGreater(result["data"]["row_count"], 0)

    def test_explain_json_version_compatibility(self):
        version_result = self.invoke("query", "--sql", "SELECT 1")
        version = tuple(map(int, version_result["data"]["execution"]["server_version"].split(".")))
        result = self.invoke("explain", "--sql", "SELECT 1", "--format", "json")
        if version < (5, 6, 5):
            self.assertEqual(result["error"]["code"], "unsupported_feature")
        else:
            self.assertTrue(result["success"], result["error"])
            self.assertIn("query_block", json.loads(result["data"]["rows"][0][0]))

    def test_authentication_failure_is_sanitized(self):
        self.entry["password"] = "deliberately-wrong-test-password"
        self.write_config()
        result = self.invoke("query", "--sql", "SELECT 1")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "access_denied")
        self.assertNotIn(self.entry["password"], json.dumps(result))

    def test_readonly_metadata_statements(self):
        for sql in ("SHOW DATABASES", "SHOW TABLES", "SHOW COLUMNS FROM TABLES",
                    "DESCRIBE TABLES", "SHOW VARIABLES LIKE 'version%'",
                    "SELECT DATABASE(), VERSION(), @@session.sql_mode"):
            with self.subTest(sql=sql):
                result = self.invoke("query", "--sql", sql, "--limit", "2")
                self.assertTrue(result["success"], result["error"])
                self.assertGreater(result["data"]["row_count"], 0)
                self.assertLessEqual(result["data"]["row_count"], 2)


if __name__ == "__main__":
    unittest.main()
