import os
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    root TEXT NOT NULL,
    total_size INTEGER NOT NULL,
    total_files INTEGER NOT NULL,
    total_dirs INTEGER NOT NULL,
    elapsed_ms INTEGER NOT NULL,
    skipped INTEGER NOT NULL DEFAULT 0,
    version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dirs (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    files INTEGER NOT NULL,
    dirs INTEGER NOT NULL,
    mtime REAL NOT NULL,
    PRIMARY KEY (snapshot_id, path)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS files (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    apparent INTEGER NOT NULL,
    mtime REAL NOT NULL,
    inode INTEGER,
    mode INTEGER,
    PRIMARY KEY (snapshot_id, path)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_snapshots_root_created
    ON snapshots(root, created_at);

CREATE INDEX IF NOT EXISTS idx_files_size
    ON files(snapshot_id, size DESC);
"""


def connect(db_path):
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def normalize_root(root):
    return str(Path(root).expanduser().absolute())


def insert_snapshot(
    conn,
    created_at,
    root,
    total_size,
    total_files,
    total_dirs,
    elapsed_ms,
    skipped,
    version,
    dirs,
    files,
):
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO snapshots
                (created_at, root, total_size, total_files, total_dirs,
                 elapsed_ms, skipped, version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                root,
                total_size,
                total_files,
                total_dirs,
                elapsed_ms,
                skipped,
                version,
            ),
        )
        snapshot_id = cursor.lastrowid
        conn.executemany(
            """
            INSERT INTO dirs (snapshot_id, path, size, files, dirs, mtime)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [(snapshot_id, *row) for row in dirs],
        )
        conn.executemany(
            """
            INSERT INTO files
                (snapshot_id, path, size, apparent, mtime, inode, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [(snapshot_id, *row) for row in files],
        )
    return snapshot_id


def get_snapshot(conn, snapshot_id):
    return conn.execute(
        "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
    ).fetchone()


def latest_snapshot(conn, root=None):
    if root is None:
        return conn.execute(
            "SELECT * FROM snapshots ORDER BY created_at DESC, id DESC LIMIT 1"
        ).fetchone()
    return conn.execute(
        """
        SELECT * FROM snapshots
        WHERE root = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (normalize_root(root),),
    ).fetchone()


def previous_snapshot(conn, snapshot):
    return conn.execute(
        """
        SELECT * FROM snapshots
        WHERE root = ?
          AND (created_at < ? OR (created_at = ? AND id < ?))
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (snapshot["root"], snapshot["created_at"], snapshot["created_at"], snapshot["id"]),
    ).fetchone()


def snapshot_at_or_before(conn, root, timestamp):
    return conn.execute(
        """
        SELECT * FROM snapshots
        WHERE root = ? AND created_at <= ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (normalize_root(root), timestamp),
    ).fetchone()


def list_snapshots(conn, root=None, limit=None):
    query = "SELECT * FROM snapshots"
    params = []
    if root is not None:
        query += " WHERE root = ?"
        params.append(normalize_root(root))
    query += " ORDER BY created_at DESC, id DESC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(int(limit))
    return conn.execute(query, params).fetchall()


def get_dirs(conn, snapshot_id):
    rows = conn.execute(
        "SELECT path, size, files, dirs, mtime FROM dirs WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchall()
    return {row["path"]: row for row in rows}


def get_files(conn, snapshot_id):
    rows = conn.execute(
        """
        SELECT path, size, apparent, mtime, inode, mode
        FROM files WHERE snapshot_id = ?
        """,
        (snapshot_id,),
    ).fetchall()
    return {row["path"]: row for row in rows}


def get_file(conn, snapshot_id, path):
    return conn.execute(
        """
        SELECT path, size, apparent, mtime, inode, mode
        FROM files WHERE snapshot_id = ? AND path = ?
        """,
        (snapshot_id, path),
    ).fetchone()


def search_files_by_size(conn, snapshot_id, size, exclude_path, limit=50):
    return conn.execute(
        """
        SELECT path, size, apparent, mtime, inode, mode
        FROM files
        WHERE snapshot_id = ? AND size = ? AND path <> ?
        ORDER BY path
        LIMIT ?
        """,
        (snapshot_id, size, exclude_path, limit),
    ).fetchall()


def delete_snapshot(conn, snapshot_id):
    with conn:
        conn.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))


def prune_snapshots(conn, keep=None, older_than=None):
    rows = conn.execute(
        "SELECT id, root, created_at FROM snapshots ORDER BY root, created_at DESC, id DESC"
    ).fetchall()
    by_root = {}
    for row in rows:
        by_root.setdefault(row["root"], []).append(row)

    delete_ids = set()
    for root_rows in by_root.values():
        for index, row in enumerate(root_rows):
            if keep is not None and index >= keep:
                delete_ids.add(row["id"])
                continue
            if older_than is not None and row["created_at"] < older_than and index > 0:
                delete_ids.add(row["id"])

    if delete_ids:
        placeholders = ",".join("?" for _ in delete_ids)
        with conn:
            conn.execute(
                f"DELETE FROM snapshots WHERE id IN ({placeholders})",
                tuple(delete_ids),
            )
    return len(delete_ids)


def vacuum(conn):
    conn.execute("VACUUM")


def database_size(conn):
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    return page_count * page_size


def find_snapshot_for_path(conn, path):
    target = Path(path).expanduser().absolute()
    rows = conn.execute(
        "SELECT * FROM snapshots ORDER BY created_at DESC, id DESC"
    ).fetchall()
    for row in rows:
        root = Path(row["root"])
        try:
            if target.is_relative_to(root):
                relative = os.path.relpath(target, root)
                if relative == ".":
                    relative = "."
                else:
                    relative = relative.replace(os.sep, "/")
                return row, relative
        except ValueError:
            continue
    return None, None
