"""Explicit lifecycle operations for normalized generation attempts."""

import copy

try:
    from .failure_diagnostics import FAILURE_SUMMARIES, parse_comfyui_failure
except ImportError:
    from failure_diagnostics import FAILURE_SUMMARIES, parse_comfyui_failure


class TaskPreparationError(Exception):
    """Raised when a task cannot be materialized before ComfyUI validation."""

    def __init__(self, failure):
        self.failure = dict(failure or {})
        super().__init__(self.failure.get("summary") or self.failure.get("code") or "task preparation failed")


class TaskService:
    def __init__(self, store, client_factory, prepare_attempt=None):
        self.store = store
        self.client_factory = client_factory
        self.prepare_attempt = prepare_attempt

    def _client(self, attempt):
        return self.client_factory(attempt.get("server_url") or "")

    def _graph(self, attempt):
        return (attempt.get("parameters") or {}).get("graph") or {}

    def list_control_tasks(self, project_name="", status_filter=""):
        attempts = self.store.list_attempts(statuses=[status_filter] if status_filter else None)
        if project_name:
            attempts = [item for item in attempts if item.get("project_name") == project_name]
        grouped = {}
        for attempt in attempts:
            grouped.setdefault(attempt["segment_key"], []).append(attempt)
        return [{"segment_key": key, "latest": rows[0], "history": rows} for key, rows in grouped.items()]

    def preflight_attempt(self, attempt_id):
        attempt = self.store.get_attempt(attempt_id)
        if not attempt:
            raise KeyError(attempt_id)
        if attempt["status"] == "preflight_failed":
            attempt = self.store.transition(attempt_id, "preflight_pending")
        client = self._client(attempt)
        try:
            if self.prepare_attempt:
                prepared = self.prepare_attempt(attempt, client)
                if isinstance(prepared, dict):
                    parameters = prepared.get("parameters")
                    if parameters is not None:
                        attempt = self.store.update_attempt(attempt_id, parameters=parameters)
            result = client.preflight(self._graph(attempt))
        except TaskPreparationError as exc:
            failure = exc.failure
            updated = self.store.transition(attempt_id, "preflight_failed", failure=failure)
            return {"status": updated["status"], "failure": failure, "severity": "block"}
        except Exception as exc:
            failure = {"code": "F-CONNECTION", "summary": FAILURE_SUMMARIES["F-CONNECTION"], "raw_error": str(exc)}
            updated = self.store.transition(attempt_id, "preflight_failed", failure=failure)
            return {"status": updated["status"], "failure": failure, "severity": "block"}
        missing_nodes = result.get("missing_nodes") or []
        missing_models = result.get("missing_models") or []
        if missing_models:
            code = "F-MODEL-MISSING"
            summary = FAILURE_SUMMARIES[code]
            detail = ", ".join(str(x) for x in missing_models)
        elif missing_nodes:
            code = "F-NODE-MISSING"
            summary = FAILURE_SUMMARIES[code]
            detail = ", ".join(str(x) for x in missing_nodes)
        else:
            code = ""
            summary = ""
            detail = ""
        if code:
            failure = {"code": code, "summary": summary, "detail": detail}
            updated = self.store.transition(attempt_id, "preflight_failed", failure=failure)
            return {"status": updated["status"], "failure": failure, "severity": "block", "preflight": result}
        warnings = list(result.get("warnings") or [])
        parameters = attempt.get("parameters") or {}
        try:
            profile = client.profile() or {}
        except Exception:
            profile = {}
        mode = str(parameters.get("mode") or "").lower()
        references = parameters.get("images") or parameters.get("references") or []
        gpu_name = str(profile.get("gpu_name") or "").lower()
        if mode == "r2v" and "3090" in gpu_name and float(parameters.get("mp") or 0) >= 1.0 and float(parameters.get("duration") or 0) >= 10 and len(references) >= 4:
            warnings.append({
                "code": "W-VRAM-HIGH",
                "summary": "RTX 3090 上的 R2V 参数显存风险高",
                "parameters": {"mp": parameters.get("mp"), "duration": parameters.get("duration"), "references": len(references)},
            })
        updated = self.store.transition(attempt_id, "ready")
        return {"status": updated["status"], "failure": None, "severity": "warning" if warnings else "pass", "warnings": warnings}

    def submit_attempt(self, attempt_id):
        attempt = self.store.get_attempt(attempt_id)
        if not attempt:
            raise KeyError(attempt_id)
        if attempt["status"] == "preflight_pending":
            self.preflight_attempt(attempt_id)
            attempt = self.store.get_attempt(attempt_id)
        if attempt["status"] != "ready":
            return attempt
        self.store.transition(attempt_id, "submitting")
        attempt = self.store.get_attempt(attempt_id)
        try:
            response = self._client(attempt).submit(self._graph(attempt))
            prompt_id = response.get("prompt_id") or response.get("id")
            if not prompt_id:
                raise RuntimeError("ComfyUI 未返回 prompt_id")
            return self.store.transition(attempt_id, "queued", prompt_id=prompt_id)
        except Exception as exc:
            failure = {"code": "F-CONNECTION", "summary": FAILURE_SUMMARIES["F-CONNECTION"], "raw_error": str(exc)}
            return self.store.transition(attempt_id, "failed", failure=failure)

    def refresh_attempt(self, attempt_id):
        attempt = self.store.get_attempt(attempt_id)
        if not attempt:
            raise KeyError(attempt_id)
        if attempt["status"] not in {"queued", "running", "cancel_requested"}:
            return attempt
        client = self._client(attempt)
        try:
            queue = client.queue() or {}
            history = client.history(attempt.get("prompt_id")) or {}
        except Exception:
            return attempt
        pid = attempt.get("prompt_id")
        running = {str(item[1]) for item in queue.get("queue_running", []) if len(item) > 1}
        pending = {str(item[1]) for item in queue.get("queue_pending", []) if len(item) > 1}
        if pid and str(pid) in running:
            if attempt["status"] == "queued":
                return self.store.transition(attempt_id, "running")
            return attempt
        if pid and str(pid) in pending:
            return attempt
        entry = history.get(str(pid)) if isinstance(history, dict) and pid else None
        if entry:
            status = entry.get("status") or {}
            messages = status.get("messages") or []
            if any(isinstance(item, (list, tuple)) and item and item[0] == "execution_error" for item in messages):
                return self.store.transition(attempt_id, "failed", failure=parse_comfyui_failure(entry))
            if status.get("completed") or entry.get("outputs"):
                return self.store.transition(attempt_id, "succeeded", output=entry.get("outputs") or {})
        count = int(attempt.get("missing_poll_count") or 0) + 1
        if count >= 2:
            return self.store.transition(attempt_id, "stale", missing_poll_count=count, failure={
                "code": "F-SERVER-STALE", "summary": FAILURE_SUMMARIES["F-SERVER-STALE"]
            })
        return self.store.update_attempt(attempt_id, missing_poll_count=count)

    def refresh_active_attempts(self):
        return [self.refresh_attempt(item["attempt_id"]) for item in self.store.list_attempts(statuses=["queued", "running", "cancel_requested"])]

    def retry_attempt(self, attempt_id, overrides=None):
        parent = self.store.get_attempt(attempt_id)
        if not parent:
            raise KeyError(attempt_id)
        parameters = copy.deepcopy(parent.get("parameters") or {})
        parameters.update(overrides or {})
        return self.store.get_attempt(self.store.create_attempt(
            segment_key=parent["segment_key"], status="preflight_pending", parameters=parameters,
            server_url=parent.get("server_url", ""), parent_attempt_id=parent["attempt_id"],
            batch_id=parent.get("batch_id"), kind=parent.get("kind", "video"),
        ))

    def cancel_attempt(self, attempt_id, confirm_interrupt=False):
        attempt = self.store.get_attempt(attempt_id)
        if not attempt:
            raise KeyError(attempt_id)
        client = self._client(attempt)
        if attempt["status"] == "queued":
            if attempt.get("prompt_id"):
                client.delete_pending(attempt["prompt_id"])
            return self.store.transition(attempt_id, "cancelled")
        if attempt["status"] == "running":
            if not confirm_interrupt:
                return {"confirmation_required": True, "task_name": attempt["segment_key"], "attempt": attempt}
            client.interrupt()
            return self.store.transition(attempt_id, "cancel_requested")
        return attempt

    def cancel_batch(self, batch_id, cancel_running=False):
        results = []
        for attempt in self.store.list_attempts():
            if attempt.get("batch_id") != batch_id:
                continue
            if attempt["status"] == "running" and not cancel_running:
                continue
            if attempt["status"] in {"queued", "running"}:
                results.append(self.cancel_attempt(attempt["attempt_id"], confirm_interrupt=cancel_running))
        return results

    def resolve_chain(self, attempt_id, predecessor_attempt_id=None, disable_chain=False):
        attempt = self.store.get_attempt(attempt_id)
        if not attempt:
            raise KeyError(attempt_id)
        parameters = copy.deepcopy(attempt.get("parameters") or {})
        if disable_chain:
            parameters["chain_mode"] = False
            parameters.pop("chain_prev", None)
        elif predecessor_attempt_id:
            predecessor = self.store.get_attempt(predecessor_attempt_id)
            if not predecessor or predecessor["status"] != "succeeded":
                raise ValueError("链式前置版本必须是成功尝试")
            parameters["chain_mode"] = True
            parameters["chain_prev"] = predecessor_attempt_id
        return self.store.transition(attempt_id, "preflight_pending", parameters=parameters)
