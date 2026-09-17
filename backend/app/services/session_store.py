import json
import sqlite3
import threading
from pathlib import Path

from backend.app.models import Session


class SessionStore:
    """SQLite-backed extraction sessions and generated export artifacts."""

    def __init__(self, db_path: str):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self):
        with self._lock, self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS extraction_sessions (id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            db.execute("CREATE TABLE IF NOT EXISTS extraction_exports (session_id TEXT NOT NULL, kind TEXT NOT NULL, payload BLOB NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(session_id, kind))")
            db.execute("CREATE TABLE IF NOT EXISTS extraction_checkpoints (session_id TEXT NOT NULL, batch_number INTEGER NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(session_id, batch_number))")

    def save(self, session: Session):
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO extraction_sessions(id,payload,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=CURRENT_TIMESTAMP",
                (session.id, session.model_dump_json()),
            )

    def get(self, session_id: str) -> Session | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT payload FROM extraction_sessions WHERE id=?", (session_id,)).fetchone()
        return Session.model_validate_json(row[0]) if row else None

    def save_export(self, session_id: str, kind: str, payload: bytes):
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO extraction_exports(session_id,kind,payload,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(session_id,kind) DO UPDATE SET payload=excluded.payload,updated_at=CURRENT_TIMESTAMP",
                (session_id, kind, payload),
            )

    def get_export(self, session_id: str, kind: str) -> bytes | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT payload FROM extraction_exports WHERE session_id=? AND kind=?", (session_id, kind)).fetchone()
        return bytes(row[0]) if row else None

    def clear_exports(self, session_id: str):
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM extraction_exports WHERE session_id=?", (session_id,))

    def save_checkpoint(self, session_id: str, batch_number: int, payload: dict):
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO extraction_checkpoints(session_id,batch_number,payload,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(session_id,batch_number) DO UPDATE SET payload=excluded.payload,updated_at=CURRENT_TIMESTAMP",
                (session_id, batch_number, json.dumps(payload, ensure_ascii=False)),
            )

    def load_checkpoints(self, session_id: str) -> list[dict]:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT payload FROM extraction_checkpoints WHERE session_id=? ORDER BY batch_number", (session_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def checkpoint_count(self, session_id: str) -> int:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT COUNT(*) FROM extraction_checkpoints WHERE session_id=?", (session_id,)).fetchone()
        return int(row[0])

    def clear_checkpoints(self, session_id: str):
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM extraction_checkpoints WHERE session_id=?", (session_id,))

    def recover_interrupted(self) -> int:
        terminal = {"READY", "COMPLETED", "COMPLETED_WITH_ERRORS", "PARTIAL_SUCCESS", "DEMO_MODE", "ERROR"}
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT payload FROM extraction_sessions").fetchall()
        recovered = 0
        for row in rows:
            session = Session.model_validate_json(row[0])
            if session.stage not in terminal:
                session.stage = "ERROR"
                session.message = "Extraction was interrupted by a server restart. Start a new extraction to continue."
                self.save(session)
                recovered += 1
        return recovered
