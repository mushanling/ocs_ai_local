import json
import sqlite3
import time
from contextlib import contextmanager


class Store:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY, created REAL NOT NULL, value TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, key, ttl):
        with self.connect() as db:
            row = db.execute("SELECT value FROM cache WHERE key=? AND created>?", (key, time.time() - ttl)).fetchone()
            return json.loads(row[0]) if row else None

    def put(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", (key, json.dumps(value, ensure_ascii=False), time.time()))
            db.execute("DELETE FROM cache WHERE key NOT IN (SELECT key FROM cache ORDER BY created DESC LIMIT 5000)")

    def log(self, value):
        with self.connect() as db:
            db.execute("INSERT INTO logs(created,value) VALUES (?,?)", (time.time(), json.dumps(value, ensure_ascii=False)))
            db.execute("DELETE FROM logs WHERE id NOT IN (SELECT id FROM logs ORDER BY id DESC LIMIT 500)")

    def logs(self):
        with self.connect() as db:
            return [dict(id=row[0], created=row[1], **json.loads(row[2])) for row in db.execute("SELECT id,created,value FROM logs ORDER BY id DESC LIMIT 100")]

    def clear(self):
        with self.connect() as db:
            db.execute("DELETE FROM cache")
