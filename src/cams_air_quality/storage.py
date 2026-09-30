"""SQLite is the transactional control plane; raw payloads never live in SQL."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class Manifest:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("""CREATE TABLE IF NOT EXISTS downloads (
                key TEXT PRIMARY KEY, dataset TEXT, variable TEXT, year INTEGER,
                month INTEGER, temporal_resolution TEXT, level_type TEXT, level INTEGER,
                request_date TEXT, download_date TEXT, filename TEXT, filepath TEXT,
                filesize INTEGER, status TEXT, checksum TEXT, error TEXT, api_request TEXT,
                remote_id TEXT, catalog_sha256 TEXT, qc_json TEXT, processed_path TEXT,
                processed_checksum TEXT, processing_error TEXT, updated_at TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, key TEXT, timestamp TEXT, status TEXT, detail TEXT)""")

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=60)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def add(self, b):
        old = self.get(b.key)
        if old and old["filepath"] != b.filepath:
            candidate = Path(b.filepath)
            relocated = (
                candidate.is_file() and old["checksum"] and sha256(candidate) == old["checksum"]
            )
            empty = not old["checksum"] and old["status"] in ("requested", "failed")
            if not (relocated or empty):
                raise ValueError(
                    "Manifest path changed: migrate payloads and verify checksums first"
                )
            with self.connect() as c:
                c.execute(
                    "UPDATE downloads SET filepath=?,filename=?,updated_at=? WHERE key=?",
                    (b.filepath, candidate.name, now(), b.key),
                )
        with self.connect() as c:
            c.execute(
                """INSERT OR IGNORE INTO downloads
                (key,dataset,variable,year,month,temporal_resolution,level_type,level,
                 request_date,filename,filepath,status,api_request,catalog_sha256,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    b.key,
                    b.dataset,
                    b.variable,
                    b.year,
                    b.month,
                    b.temporal_resolution,
                    b.level_type,
                    b.level,
                    now(),
                    Path(b.filepath).name,
                    b.filepath,
                    "requested",
                    json.dumps(b.api_request, sort_keys=True),
                    b.catalog_sha256,
                    now(),
                ),
            )

    def get(self, key):
        with self.connect() as c:
            r = c.execute("SELECT * FROM downloads WHERE key=?", (key,)).fetchone()
            return dict(r) if r else None

    def set(self, key, status, **fields):
        allowed = {
            "download_date",
            "filesize",
            "checksum",
            "error",
            "remote_id",
            "qc_json",
            "processed_path",
            "processed_checksum",
            "processing_error",
        }
        if not fields.keys() <= allowed:
            raise ValueError("Unsupported manifest update")
        if status not in {
            "requested",
            "downloading",
            "downloaded",
            "validated",
            "failed",
            "processed",
        }:
            raise ValueError(status)
        fields.update(status=status, updated_at=now())
        with self.connect() as c:
            c.execute(
                "UPDATE downloads SET " + ",".join(f"{k}=?" for k in fields) + " WHERE key=?",
                [*fields.values(), key],
            )
            c.execute(
                "INSERT INTO events (key,timestamp,status,detail) VALUES (?,?,?,?)",
                (key, now(), status, json.dumps(fields)),
            )

    def rows(self):
        with self.connect() as c:
            return [
                dict(r) for r in c.execute("SELECT * FROM downloads ORDER BY year,month,variable")
            ]

    def intact(self, row):
        p = Path(row["filepath"])
        return (
            row["status"] in ("validated", "processed")
            and p.is_file()
            and p.stat().st_size == row["filesize"]
            and sha256(p) == row["checksum"]
        )
