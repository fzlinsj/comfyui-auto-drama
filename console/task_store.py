"""Normalized persistence for generation attempts and service diagnostics."""

import json
import sqlite3
import time
import uuid


ALLOWED_TRANSITIONS = {
    "preflight_pending": {"preflight_failed", "ready", "cancelled"},
    "preflight_failed": {"preflight_pending", "cancelled"},
    "ready": {"submitting", "cancelled"},
    "submitting": {"queued", "failed", "cancelled"},
    "queued": {"running", "succeeded", "failed", "cancel_requested", "cancelled", "stale"},
    "running": {"succeeded", "failed", "cancel_requested", "cancelled", "stale"},
    "cancel_requested": {"cancelled", "succeeded", "failed"},
    "blocked": {"preflight_pending", "cancelled"},
    "failed": {"preflight_pending"},
    "cancelled": {"preflight_pending"},
    "stale": {"preflight_pending"},
    "succeeded": {"preflight_pending"},
}

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "stale"}


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True) if value is not None else None


def _unjson(value, default=None):
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class TaskStore:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        self.initialize()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self):
        conn = self._connect()
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS task_segments (
                    segment_key TEXT PRIMARY KEY,
                    project_name TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    legacy_task_id TEXT UNIQUE,
                    segment_key TEXT NOT NULL,
                    parent_attempt_id TEXT,
                    batch_id TEXT,
                    kind TEXT NOT NULL DEFAULT 'video',
                    status TEXT NOT NULL,
                    server_url TEXT NOT NULL DEFAULT '',
                    server_fingerprint TEXT NOT NULL DEFAULT '',
                    prompt_id TEXT,
                    parameters_json TEXT NOT NULL,
                    output_json TEXT,
                    failure_json TEXT,
                    missing_poll_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    submitted_at TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(segment_key) REFERENCES task_segments(segment_key)
                );
                CREATE TABLE IF NOT EXISTS diagnostic_runs (
                    run_id TEXT PRIMARY KEY,
                    service TEXT NOT NULL,
                    level TEXT NOT NULL,
                    status TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    result_json TEXT,
                    failure_json TEXT,
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_attempts_segment_created
                ON task_attempts(segment_key, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_attempts_prompt
                ON task_attempts(prompt_id);
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _ensure_segment(self, conn, segment_key, display_name=None, project_name=""):
        now = _now()
        segment_key = str(segment_key or "")
        display_name = str(display_name or segment_key)
        conn.execute(
            "INSERT INTO task_segments(segment_key, project_name, display_name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(segment_key) DO UPDATE SET updated_at=excluded.updated_at",
            (segment_key, str(project_name or ""), display_name, now, now),
        )

    def create_attempt(self, segment_key, status="preflight_pending", parameters=None, **kwargs):
        if status not in ALLOWED_TRANSITIONS and status != "preflight_pending":
            raise ValueError(f"unknown task status: {status}")
        now = _now()
        attempt_id = str(kwargs.pop("attempt_id", None) or uuid.uuid4().hex)
        conn = self._connect()
        try:
            self._ensure_segment(conn, segment_key, kwargs.get("display_name"), kwargs.get("project_name"))
            conn.execute(
                """INSERT INTO task_attempts(
                    attempt_id, legacy_task_id, segment_key, parent_attempt_id, batch_id, kind, status,
                    server_url, server_fingerprint, prompt_id, parameters_json, output_json, failure_json,
                    missing_poll_count, created_at, submitted_at, started_at, finished_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    attempt_id, kwargs.get("legacy_task_id"), str(segment_key), kwargs.get("parent_attempt_id"),
                    kwargs.get("batch_id"), kwargs.get("kind", "video"), status,
                    kwargs.get("server_url", ""), kwargs.get("server_fingerprint", ""), kwargs.get("prompt_id"),
                    _json(parameters or {}), _json(kwargs.get("output")), _json(kwargs.get("failure")),
                    int(kwargs.get("missing_poll_count", 0)), kwargs.get("created_at", now),
                    kwargs.get("submitted_at"), kwargs.get("started_at"), kwargs.get("finished_at"), now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return attempt_id

    def _row(self, row):
        if row is None:
            return None
        item = dict(row)
        item["parameters"] = _unjson(item.pop("parameters_json"), {})
        item["output"] = _unjson(item.pop("output_json"), None)
        item["failure"] = _unjson(item.pop("failure_json"), None)
        return item

    def get_attempt(self, attempt_id):
        conn = self._connect()
        try:
            return self._row(conn.execute("SELECT * FROM task_attempts WHERE attempt_id = ?", (attempt_id,)).fetchone())
        finally:
            conn.close()

    def list_attempts(self, segment_key=None, statuses=None):
        clauses, values = [], []
        if segment_key:
            clauses.append("segment_key = ?")
            values.append(segment_key)
        if statuses:
            statuses = list(statuses)
            clauses.append("status IN (" + ",".join("?" for _ in statuses) + ")")
            values.extend(statuses)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM task_attempts" + where + " ORDER BY created_at DESC", values).fetchall()
            return [self._row(row) for row in rows]
        finally:
            conn.close()

    def transition(self, attempt_id, new_status, **fields):
        attempt = self.get_attempt(attempt_id)
        if not attempt:
            raise KeyError(attempt_id)
        old_status = attempt["status"]
        if new_status not in ALLOWED_TRANSITIONS.get(old_status, set()):
            raise ValueError(f"illegal task transition {old_status} -> {new_status}")
        now = _now()
        assignments = ["status = ?", "updated_at = ?"]
        values = [new_status, now]
        if new_status == "submitting" and not attempt.get("submitted_at"):
            assignments.append("submitted_at = ?")
            values.append(now)
        if new_status == "running" and not attempt.get("started_at"):
            assignments.append("started_at = ?")
            values.append(now)
        if new_status in TERMINAL_STATUSES:
            assignments.append("finished_at = ?")
            values.append(now)
        allowed = {
            "prompt_id": "prompt_id", "server_url": "server_url", "server_fingerprint": "server_fingerprint",
            "missing_poll_count": "missing_poll_count", "output": "output_json", "failure": "failure_json",
            "parameters": "parameters_json",
        }
        for key, column in allowed.items():
            if key in fields:
                assignments.append(f"{column} = ?")
                values.append(_json(fields[key]) if key in {"output", "failure", "parameters"} else fields[key])
        values.append(attempt_id)
        conn = self._connect()
        try:
            conn.execute("UPDATE task_attempts SET " + ", ".join(assignments) + " WHERE attempt_id = ?", values)
            conn.commit()
        finally:
            conn.close()
        return self.get_attempt(attempt_id)

    def update_attempt(self, attempt_id, **fields):
        attempt = self.get_attempt(attempt_id)
        if not attempt:
            raise KeyError(attempt_id)
        assignments, values = [], []
        allowed = {
            "prompt_id": "prompt_id", "server_url": "server_url", "server_fingerprint": "server_fingerprint",
            "missing_poll_count": "missing_poll_count", "output": "output_json", "failure": "failure_json",
            "parameters": "parameters_json", "submitted_at": "submitted_at", "started_at": "started_at",
            "finished_at": "finished_at",
        }
        for key, column in allowed.items():
            if key in fields:
                assignments.append(f"{column} = ?")
                values.append(_json(fields[key]) if key in {"output", "failure", "parameters"} else fields[key])
        if not assignments:
            return attempt
        assignments.append("updated_at = ?")
        values.extend([_now(), attempt_id])
        conn = self._connect()
        try:
            conn.execute("UPDATE task_attempts SET " + ", ".join(assignments) + " WHERE attempt_id = ?", values)
            conn.commit()
        finally:
            conn.close()
        return self.get_attempt(attempt_id)

    def migrate_legacy_tasks(self, tasks, server_url):
        conn = self._connect()
        try:
            for task in tasks or []:
                if not isinstance(task, dict):
                    continue
                legacy_id = str(task.get("id") or "")
                if not legacy_id:
                    continue
                exists = conn.execute("SELECT 1 FROM task_attempts WHERE legacy_task_id = ?", (legacy_id,)).fetchone()
                if exists:
                    continue
                name = str(task.get("name") or legacy_id)
                error = task.get("error")
                error_text = error if isinstance(error, str) else str((error or {}).get("message") or "")
                error_code = "F-LOST" if "F-LOST" in error_text else "F-GENERATION"
                if task.get("output_file") or task.get("downloaded"):
                    status = "succeeded"
                elif error:
                    status = "stale" if "F-LOST" in error_text else "failed"
                elif task.get("chain_waiting") and not task.get("prompt_id"):
                    status = "blocked"
                elif task.get("prompt_id"):
                    status = "queued"
                else:
                    status = "ready"
                created_at = str(task.get("created_at") or task.get("submitted_at") or _now())
                self._ensure_segment(conn, task.get("segment_key") or name, name, task.get("project_name", ""))
                failure = None
                if error:
                    failure = {
                        "code": (error.get("code") if isinstance(error, dict) else error_code),
                        "message": error_text,
                    }
                conn.execute(
                    """INSERT INTO task_attempts(
                        attempt_id, legacy_task_id, segment_key, kind, status, server_url, prompt_id,
                        parameters_json, output_json, failure_json, created_at, submitted_at, finished_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        uuid.uuid4().hex, legacy_id, str(task.get("segment_key") or name), task.get("kind", "video"),
                        status, str(server_url or ""), task.get("prompt_id"), _json({"legacy": task}),
                        _json(task.get("output_file")), _json(failure), created_at,
                        task.get("submitted_at"), task.get("finished_at") if status in TERMINAL_STATUSES else None, _now(),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def create_diagnostic_run(self, service, level, parameters):
        run_id = uuid.uuid4().hex
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO diagnostic_runs(run_id, service, level, status, parameters_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, str(service), str(level), "running", _json(parameters or {}), _now()),
            )
            conn.commit()
        finally:
            conn.close()
        return run_id

    def finish_diagnostic_run(self, run_id, status, result=None, failure=None):
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE diagnostic_runs SET status = ?, result_json = ?, failure_json = ?, finished_at = ? WHERE run_id = ?",
                (status, _json(result), _json(failure), _now(), run_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_diagnostic_run(self, run_id):
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM diagnostic_runs WHERE run_id = ?", (run_id,)).fetchone()
            if not row:
                return None
            item = dict(row)
            item["parameters"] = _unjson(item.pop("parameters_json"), {})
            item["result"] = _unjson(item.pop("result_json"), None)
            item["failure"] = _unjson(item.pop("failure_json"), None)
            return item
        finally:
            conn.close()
