import sqlite3
from datetime import datetime, timezone
from typing import List, Optional


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS boards (
            slug TEXT PRIMARY KEY,
            display_name TEXT,
            default_version TEXT,
            created_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS versions (
            board_slug TEXT,
            version TEXT,
            uploaded_at TEXT,
            description TEXT,
            PRIMARY KEY (board_slug, version),
            FOREIGN KEY (board_slug) REFERENCES boards(slug)
        )
        """
    )
    conn.commit()
    return conn


def list_boards(conn: sqlite3.Connection) -> List[dict]:
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT slug, display_name, default_version, created_at FROM boards")
    rows = cur.fetchall()
    conn.row_factory = None
    return [dict(r) for r in rows]


def list_versions(conn: sqlite3.Connection, slug: str) -> List[dict]:
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "SELECT board_slug, version, uploaded_at, description FROM versions WHERE board_slug = ?",
        (slug,),
    )
    rows = cur.fetchall()
    conn.row_factory = None
    return [dict(r) for r in rows]


def get_default_version(conn: sqlite3.Connection, slug: str) -> Optional[str]:
    row = conn.execute("SELECT default_version FROM boards WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        return None
    if row[0]:
        return row[0]
    max_row = conn.execute(
        "SELECT max(version) FROM versions WHERE board_slug = ?", (slug,)
    ).fetchone()
    return max_row[0] if max_row else None


def set_default_version(conn: sqlite3.Connection, slug: str, version: str) -> None:
    conn.execute("UPDATE boards SET default_version = ? WHERE slug = ?", (version, slug))
    conn.commit()


def upsert_board(conn: sqlite3.Connection, slug: str, display_name: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO boards (slug, display_name, created_at) VALUES (?, ?, ?)",
        (slug, display_name, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def upsert_version(
    conn: sqlite3.Connection, board_slug: str, version: str, description: str = ""
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO versions (board_slug, version, uploaded_at, description)
        VALUES (?, ?, ?, ?)
        """,
        (board_slug, version, datetime.now(timezone.utc).isoformat(), description),
    )
    conn.commit()
