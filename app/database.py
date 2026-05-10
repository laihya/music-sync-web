import sqlite3
import os
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta

logger = logging.getLogger("database")
DB_PATH = os.path.join(os.environ.get("DATA_DIR", "/data"), "music_sync.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_files (
    source_path TEXT PRIMARY KEY,
    sha256 TEXT,
    dest_path TEXT,
    status TEXT,
    artist TEXT,
    title TEXT,
    album TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS failure_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT,
    failed_path TEXT,
    reason TEXT,
    partial_artist TEXT,
    partial_title TEXT,
    partial_album TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS metadata_cache (
    file_hash TEXT PRIMARY KEY,
    source_path TEXT,
    artist TEXT,
    title TEXT,
    album TEXT,
    source TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def is_file_processed(source_path):
    with get_db() as db:
        row = db.execute("SELECT 1 FROM processed_files WHERE source_path=?", (source_path,)).fetchone()
        return row is not None


def add_processed_record(source_path, sha256, dest_path, artist=None, title=None, album=None, status='success'):
    with get_db() as db:
        db.execute("INSERT OR REPLACE INTO processed_files (source_path, sha256, dest_path, status, artist, title, album) VALUES (?,?,?,?,?,?,?)",
                   (source_path, sha256, dest_path, status, artist, title, album))


def add_failure_record(source_path, failed_path, reason, artist=None, title=None, album=None):
    with get_db() as db:
        db.execute("INSERT INTO failure_log (source_path, failed_path, reason, partial_artist, partial_title, partial_album) VALUES (?,?,?,?,?,?)",
                   (source_path, failed_path, reason, artist, title, album))


def get_failure_list():
    with get_db() as db:
        rows = db.execute("SELECT * FROM failure_log ORDER BY timestamp DESC").fetchall()
        return [dict(r) for r in rows]


def update_failure_metadata(failure_id, artist, title):
    with get_db() as db:
        db.execute("UPDATE failure_log SET partial_artist=?, partial_title=? WHERE id=?", (artist, title, failure_id))


def delete_failure_record(failure_id):
    with get_db() as db:
        db.execute("DELETE FROM failure_log WHERE id=?", (failure_id,))


def cache_metadata(file_hash, source_path, artist, title, album, source):
    with get_db() as db:
        db.execute("INSERT OR REPLACE INTO metadata_cache (file_hash, source_path, artist, title, album, source) VALUES (?,?,?,?,?,?)",
                   (file_hash, source_path, artist, title, album, source))


def get_cached_metadata(file_hash):
    with get_db() as db:
        row = db.execute("SELECT artist, title, album, source FROM metadata_cache WHERE file_hash=?", (file_hash,)).fetchone()
        return dict(row) if row else None


def cleanup_old_records(days=90):
    cutoff = datetime.now() - timedelta(days=days)
    with get_db() as db:
        db.execute("DELETE FROM processed_files WHERE timestamp < ?", (cutoff,))
        db.execute("DELETE FROM failure_log WHERE timestamp < ?", (cutoff,))
        db.execute("DELETE FROM metadata_cache WHERE timestamp < ?", (cutoff,))
    logger.info("清理了 %d 天前的记录", days)