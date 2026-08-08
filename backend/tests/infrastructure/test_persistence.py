from pathlib import Path

import pytest

from infra.persistence import SQLiteDatabase


def test_sqlite_database_creates_parent_and_commits_transaction(tmp_path: Path):
    database = SQLiteDatabase(tmp_path / "nested" / "state.db")
    with database.transaction() as connection:
        connection.execute("CREATE TABLE items (name TEXT NOT NULL)")
        connection.execute("INSERT INTO items(name) VALUES (?)", ("ready",))

    row = database.connection.execute("SELECT name FROM items").fetchone()
    assert row[0] == "ready"
    database.close()


def test_sqlite_database_rolls_back_failed_transaction(tmp_path: Path):
    database = SQLiteDatabase(tmp_path / "state.db")
    with database.transaction() as connection:
        connection.execute("CREATE TABLE items (name TEXT NOT NULL)")

    with pytest.raises(RuntimeError):
        with database.transaction() as connection:
            connection.execute("INSERT INTO items(name) VALUES (?)", ("discard",))
            raise RuntimeError("abort")

    assert database.connection.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0
    database.close()


def test_sqlite_database_close_is_idempotent(tmp_path: Path):
    database = SQLiteDatabase(tmp_path / "state.db")
    database.close()
    database.close()
