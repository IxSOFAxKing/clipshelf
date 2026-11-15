"""SQLite storage. One short-lived connection per operation (WAL mode)."""
import re
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    steam_appid   INTEGER,
    steam_name    TEXT,
    -- pending: not looked up yet; matched: found on Steam;
    -- none: no good match; manual: set by the admin (never auto-changed)
    lookup_status TEXT NOT NULL DEFAULT 'pending',
    has_cover     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS clips (
    id          TEXT PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,      -- relative to CLIPS_DIR
    filename    TEXT NOT NULL,
    title       TEXT NOT NULL,
    game_id     INTEGER REFERENCES games(id) ON DELETE SET NULL,
    game_locked INTEGER NOT NULL DEFAULT 0, -- game chosen by hand
    size        INTEGER NOT NULL,
    mtime       REAL NOT NULL,
    duration    REAL,
    width       INTEGER,
    height      INTEGER,
    vcodec      TEXT,
    audio_tracks INTEGER NOT NULL DEFAULT 0,
    merged_audio INTEGER NOT NULL DEFAULT 0, -- mixed copy exists in MEDIA_DIR
    recorded_at TEXT NOT NULL,              -- ISO local time
    added_at    TEXT NOT NULL DEFAULT (datetime('now')),
    visibility  TEXT NOT NULL DEFAULT 'private',
    favorite    INTEGER NOT NULL DEFAULT 0,
    views       INTEGER NOT NULL DEFAULT 0,
    missing     INTEGER NOT NULL DEFAULT 0  -- file no longer in CLIPS_DIR
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL          -- JSON
);
CREATE INDEX IF NOT EXISTS clips_game ON clips(game_id);
CREATE INDEX IF NOT EXISTS clips_recorded ON clips(recorded_at);
"""


# Columns added after the first release (applied to existing databases on start).
MIGRATIONS = [
    ("games", "description", "TEXT"),
    ("games", "release_date", "TEXT"),
    ("games", "developer", "TEXT"),
    ("games", "genres", "TEXT"),
    ("games", "has_hero", "INTEGER NOT NULL DEFAULT 0"),
    ("games", "art_locked", "INTEGER NOT NULL DEFAULT 0"),   # artwork chosen by hand
    ("games", "art_v", "INTEGER NOT NULL DEFAULT 0"),        # bumps when artwork changes
    ("clips", "thumb_v", "INTEGER NOT NULL DEFAULT 0"),
    ("clips", "thumb_custom", "INTEGER NOT NULL DEFAULT 0"), # thumbnail frame chosen by hand
]


@contextmanager
def connect():
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init() -> None:
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        for table, column, definition in MIGRATIONS:
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower().replace("&", "and"))


def get_or_create_game(conn: sqlite3.Connection, name: str) -> int:
    """Find a game by name, ignoring case and punctuation, so "Counter Strike 2"
    from a file name lands in an existing "Counter-Strike 2"."""
    name = " ".join(name.split())
    row = conn.execute("SELECT id FROM games WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    key = _key(name)
    if key:
        for row in conn.execute("SELECT id, name FROM games"):
            if _key(row["name"]) == key:
                return row["id"]
    return conn.execute("INSERT INTO games (name) VALUES (?)", (name,)).lastrowid


def prune_empty_games(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute(
        "SELECT id FROM games WHERE id NOT IN "
        "(SELECT DISTINCT game_id FROM clips WHERE game_id IS NOT NULL)"
    ).fetchall()
    ids = [r["id"] for r in rows]
    conn.executemany("DELETE FROM games WHERE id = ?", [(i,) for i in ids])
    return ids
