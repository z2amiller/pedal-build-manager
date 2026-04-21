import pytest

from app.db import (
    get_default_version,
    init_db,
    list_boards,
    list_versions,
    set_default_version,
    upsert_board,
    upsert_version,
)


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


def test_init_db_creates_tables(conn):
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "boards" in tables
    assert "versions" in tables


def test_upsert_board_and_list(conn):
    upsert_board(conn, "ts808", "TS-808 Overdrive")
    boards = list_boards(conn)
    assert len(boards) == 1
    assert boards[0]["slug"] == "ts808"
    assert boards[0]["display_name"] == "TS-808 Overdrive"
    assert boards[0]["created_at"] is not None


def test_upsert_board_ignore_duplicate(conn):
    upsert_board(conn, "ts808", "TS-808 Overdrive")
    upsert_board(conn, "ts808", "Different Name")
    boards = list_boards(conn)
    assert len(boards) == 1
    assert boards[0]["display_name"] == "TS-808 Overdrive"


def test_upsert_version_and_list(conn):
    upsert_board(conn, "ts808", "TS-808 Overdrive")
    upsert_version(conn, "ts808", "1.0", "Initial release")
    upsert_version(conn, "ts808", "1.1", "Bug fix")
    versions = list_versions(conn, "ts808")
    assert len(versions) == 2
    slugs = {v["version"] for v in versions}
    assert {"1.0", "1.1"} == slugs


def test_upsert_version_replace(conn):
    upsert_board(conn, "ts808", "TS-808 Overdrive")
    upsert_version(conn, "ts808", "1.0", "Original")
    upsert_version(conn, "ts808", "1.0", "Updated")
    versions = list_versions(conn, "ts808")
    assert len(versions) == 1
    assert versions[0]["description"] == "Updated"


def test_upsert_version_sets_uploaded_at(conn):
    upsert_board(conn, "ts808", "TS-808 Overdrive")
    upsert_version(conn, "ts808", "1.0")
    versions = list_versions(conn, "ts808")
    assert versions[0]["uploaded_at"] is not None


def test_list_versions_empty(conn):
    upsert_board(conn, "ts808", "TS-808 Overdrive")
    assert list_versions(conn, "ts808") == []


def test_get_default_version_explicit(conn):
    upsert_board(conn, "ts808", "TS-808 Overdrive")
    upsert_version(conn, "ts808", "1.0")
    upsert_version(conn, "ts808", "2.0")
    set_default_version(conn, "ts808", "1.0")
    assert get_default_version(conn, "ts808") == "1.0"


def test_get_default_version_fallback_to_max(conn):
    upsert_board(conn, "ts808", "TS-808 Overdrive")
    upsert_version(conn, "ts808", "1.0")
    upsert_version(conn, "ts808", "2.0")
    assert get_default_version(conn, "ts808") == "2.0"


def test_get_default_version_no_versions(conn):
    upsert_board(conn, "ts808", "TS-808 Overdrive")
    assert get_default_version(conn, "ts808") is None


def test_get_default_version_unknown_board(conn):
    assert get_default_version(conn, "nonexistent") is None


def test_set_default_version(conn):
    upsert_board(conn, "ts808", "TS-808 Overdrive")
    upsert_version(conn, "ts808", "1.0")
    set_default_version(conn, "ts808", "1.0")
    row = conn.execute("SELECT default_version FROM boards WHERE slug = ?", ("ts808",)).fetchone()
    assert row[0] == "1.0"


def test_list_boards_empty(conn):
    assert list_boards(conn) == []
