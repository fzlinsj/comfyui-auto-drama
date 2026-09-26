"""Normalized persistence for generation attempts and service diagnostics."""

import json
import sqlite3
import time
import uuid


ALLOWED_TRANSITIONS = {
    "preflight_pending": {"preflight_failed", "ready", "cancelled"},
    "preflight_failed": {"preflight_pending", "ready", "cancelled"},
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

                CREATE TABLE IF NOT EXISTS environment_targets (
                    target_id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    host TEXT NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    port INTEGER NOT NULL DEFAULT 22,
                    credential_ref TEXT NOT NULL DEFAULT '',
                    fingerprint TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'disconnected',
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS environment_scans (
                    scan_id TEXT PRIMARY KEY,
                    target_id TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    raw_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(target_id) REFERENCES environment_targets(target_id)
                );
                CREATE TABLE IF NOT EXISTS deployment_plans (
                    plan_id TEXT PRIMARY KEY,
                    target_id TEXT NOT NULL,
                    scan_id TEXT NOT NULL,
                    recipe_id TEXT NOT NULL,
                    recipe_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    estimate_json TEXT NOT NULL,
                    diff_json TEXT,
                    risk_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(target_id) REFERENCES environment_targets(target_id),
                    FOREIGN KEY(scan_id) REFERENCES environment_scans(scan_id)
                );
                CREATE TABLE IF NOT EXISTS deployment_steps (
                    step_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    step_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    details_json TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(plan_id, step_name),
                    FOREIGN KEY(plan_id) REFERENCES deployment_plans(plan_id)
                );
                CREATE TABLE IF NOT EXISTS environment_manifests (
                    manifest_id TEXT PRIMARY KEY,
                    target_id TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    FOREIGN KEY(target_id) REFERENCES environment_targets(target_id)
                );
                CREATE INDEX IF NOT EXISTS idx_environment_scans_target
                ON environment_scans(target_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_deployment_plans_target
                ON deployment_plans(target_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_deployment_steps_plan
                ON deployment_steps(plan_id, step_id);
                """
            )
            conn.commit()
        finally:
            conn.close()

    def table_columns(self, table_name):
        """Return SQLite column names for migration and security tests."""
        allowed = {
            "environment_targets", "environment_scans", "deployment_plans",
            "deployment_steps", "environment_manifests",
        }
        if table_name not in allowed:
            raise ValueError(f"unsupported table: {table_name}")
        conn = self._connect()
        try:
            return [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]
        finally:
            conn.close()

    def create_environment_target(self, platform, host, username="", port=22,
                                  credential_ref="", fingerprint="", metadata=None):
        target_id = uuid.uuid4().hex
        now = _now()
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO environment_targets(
                    target_id, platform, host, username, port, credential_ref,
                    fingerprint, status, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'disconnected', ?, ?, ?)""",
                (target_id, str(platform or ""), str(host or ""), str(username or ""),
                 int(port or 22), str(credential_ref or ""), str(fingerprint or ""),
                 _json(metadata or {}), now, now),
            )
            conn.commit()
        finally:
            conn.close()
        return target_id

    def find_environment_target(self, platform, host, username="", port=22):
        """Find the newest target matching the normalized SSH identity."""
        conn = self._connect()
        try:
            row = conn.execute(
                """SELECT * FROM environment_targets
                   WHERE platform = ? AND host = ? AND username = ? AND port = ?
                   ORDER BY updated_at DESC LIMIT 1""",
                (str(platform or ""), str(host or ""), str(username or ""), int(port or 22)),
            ).fetchone()
            return self._environment_row(row, {})
        finally:
            conn.close()

    def update_environment_target_fingerprint(self, target_id, fingerprint, status="scanned"):
        """Update only the trusted fingerprint and scan status."""
        now = _now()
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE environment_targets SET fingerprint = ?, status = ?, updated_at = ? WHERE target_id = ?",
                (str(fingerprint or ""), str(status or "scanned"), now, str(target_id)),
            )
            conn.commit()
        finally:
            conn.close()

    def save_environment_scan(self, target_id, summary, raw=None):
        scan_id = uuid.uuid4().hex
        now = _now()
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO environment_scans(scan_id, target_id, summary_json, raw_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (scan_id, target_id, _json(summary or {}), _json(raw) if raw is not None else None, now),
            )
            conn.execute(
                "UPDATE environment_targets SET status = 'scanned', updated_at = ? WHERE target_id = ?",
                (now, target_id),
            )
            conn.commit()
        finally:
            conn.close()
        return scan_id

    def get_environment_scan(self, scan_id):
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM environment_scans WHERE scan_id = ?", (scan_id,)).fetchone()
            return self._environment_row(row, {"summary_json": "summary", "raw_json": "raw"})
        finally:
            conn.close()

    def save_deployment_plan(self, target_id, scan_id, recipe_id, recipe_version, estimate,
                             diff=None, risks=None, status=None):
        plan_id = uuid.uuid4().hex
        now = _now()
        plan_status = status or (estimate or {}).get("status") or "plan_ready"
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO deployment_plans(
                    plan_id, target_id, scan_id, recipe_id, recipe_version, status,
                    estimate_json, diff_json, risk_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (plan_id, target_id, scan_id, recipe_id, recipe_version, plan_status,
                 _json(estimate or {}), _json(diff or {}), _json(risks or []), now, now),
            )
            conn.execute(
                "UPDATE environment_targets SET status = ?, updated_at = ? WHERE target_id = ?",
                (plan_status, now, target_id),
            )
            conn.commit()
        finally:
            conn.close()
        return plan_id

    def get_deployment_plan(self, plan_id):
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM deployment_plans WHERE plan_id = ?", (plan_id,)).fetchone()
            return self._environment_row(row, {"estimate_json": "estimate", "diff_json": "diff", "risk_json": "risks"})
        finally:
            conn.close()

    def upsert_deployment_step(self, plan_id, step_name, status, details=None, attempts=None):
        now = _now()
        step_id = uuid.uuid4().hex
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT step_id, attempts FROM deployment_steps WHERE plan_id = ? AND step_name = ?",
                (plan_id, step_name),
            ).fetchone()
            next_attempts = int(attempts if attempts is not None else ((existing[1] if existing else 0) + 1))
            if existing:
                conn.execute(
                    """UPDATE deployment_steps SET status = ?, details_json = ?, attempts = ?,
                       started_at = COALESCE(started_at, ?), finished_at = ?, updated_at = ?
                       WHERE step_id = ?""",
                    (status, _json(details or {}), next_attempts, now,
                     now if status in {"succeeded", "failed", "interrupted"} else None, now, existing[0]),
                )
            else:
                conn.execute(
                    """INSERT INTO deployment_steps(
                        step_id, plan_id, step_name, status, details_json, attempts,
                        started_at, finished_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (step_id, plan_id, step_name, status, _json(details or {}), next_attempts,
                     now, now if status in {"succeeded", "failed", "interrupted"} else None, now),
                )
            conn.commit()
        finally:
            conn.close()

    def save_environment_manifest(self, target_id, manifest):
        manifest_id = uuid.uuid4().hex
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO environment_manifests(manifest_id, target_id, manifest_json, generated_at) VALUES (?, ?, ?, ?)",
                (manifest_id, target_id, _json(manifest or {}), _now()),
            )
            conn.commit()
        finally:
            conn.close()
        return manifest_id

    def get_environment_manifest(self, target_id):
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM environment_manifests WHERE target_id = ? ORDER BY generated_at DESC LIMIT 1",
                (target_id,),
            ).fetchone()
            return self._environment_row(row, {"manifest_json": "manifest"})
        finally:
            conn.close()

    def get_environment_job(self, plan_id):
        conn = self._connect()
        try:
            plan = conn.execute("SELECT * FROM deployment_plans WHERE plan_id = ?", (plan_id,)).fetchone()
            if not plan:
                return None
            target = conn.execute(
                "SELECT * FROM environment_targets WHERE target_id = ?", (plan["target_id"],)
            ).fetchone()
            scan = conn.execute(
                "SELECT * FROM environment_scans WHERE scan_id = ?", (plan["scan_id"],)
            ).fetchone()
            steps = conn.execute(
                "SELECT * FROM deployment_steps WHERE plan_id = ? ORDER BY step_id", (plan_id,)
            ).fetchall()
            manifest = conn.execute(
                "SELECT * FROM environment_manifests WHERE target_id = ? ORDER BY generated_at DESC LIMIT 1",
                (plan["target_id"],),
            ).fetchone()
            return {
                "plan": self._environment_row(plan, {"estimate_json": "estimate", "diff_json": "diff", "risk_json": "risks"}),
                "target": self._environment_row(target, {"metadata_json": "metadata"}),
                "scan": self._environment_row(scan, {"summary_json": "summary", "raw_json": "raw"}),
                "steps": [self._environment_row(step, {"details_json": "details"}) for step in steps],
                "manifest": self._environment_row(manifest, {"manifest_json": "manifest"}) if manifest else None,
            }
        finally:
            conn.close()

    @staticmethod
    def _environment_row(row, json_fields):
        if row is None:
            return None
        item = dict(row)
        for source, target in json_fields.items():
            item[target] = _unjson(item.pop(source, None), {} if target not in {"raw"} else None)
        return item

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
            rows = conn.execute(
                "SELECT task_attempts.*, task_segments.project_name, task_segments.display_name "
                "FROM task_attempts JOIN task_segments ON task_segments.segment_key = task_attempts.segment_key"
                + where.replace(" WHERE ", " WHERE task_attempts.")
                + " ORDER BY task_attempts.created_at DESC", values
            ).fetchall()
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
