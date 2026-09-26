"""Application facade for cloud environment scan, planning and deployment."""

from __future__ import annotations

import dataclasses
import threading
import uuid
from pathlib import Path

try:
    from .environment_deployer import EnvironmentDeployer
    from .environment_models import EnvironmentError, redact_environment_data
    from .environment_planner import build_plan
    from .environment_recipes import load_recipe
    from .environment_scanner import EnvironmentScanner
    from .environment_ssh import parse_ssh_command, SSHSession
    from .environment_downloader import RemoteDownloader
except ImportError:
    from environment_deployer import EnvironmentDeployer
    from environment_models import EnvironmentError, redact_environment_data
    from environment_planner import build_plan
    from environment_recipes import load_recipe
    from environment_scanner import EnvironmentScanner
    from environment_ssh import parse_ssh_command, SSHSession
    from environment_downloader import RemoteDownloader


def _strip_fingerprint_fields(value):
    if isinstance(value, dict):
        return {
            key: _strip_fingerprint_fields(item)
            for key, item in value.items()
            if str(key).lower() not in {"fingerprint", "host_fingerprint"}
        }
    if isinstance(value, list):
        return [_strip_fingerprint_fields(item) for item in value]
    return value


class EnvironmentManager:
    def __init__(self, store, session_factory=None, downloader_factory=None):
        self.store = store
        self.session_factory = session_factory or (lambda connection, credential=None: SSHSession(connection, credential=credential))
        self.downloader_factory = downloader_factory
        self._sessions = {}
        self._plans = {}
        self._deployers = {}
        self._jobs = {}
        self._lock = threading.RLock()

    def scan_target(self, payload):
        payload = dict(payload or {})
        connection = parse_ssh_command(payload.get("ssh_command"))
        credential = {}
        if payload.get("password"):
            credential["password"] = payload["password"]
        if payload.get("private_key"):
            credential["private_key"] = payload["private_key"]
        existing = self.store.find_environment_target(
            payload.get("platform") or "unknown",
            connection.host,
            connection.username,
            connection.port,
        )
        if existing and existing.get("fingerprint"):
            credential["fingerprint"] = existing["fingerprint"]
        session = self.session_factory(connection, credential=credential)
        observed_fingerprint = session.observe_fingerprint()
        expected_fingerprint = str((existing or {}).get("fingerprint") or "")
        retrust = bool(payload.get("retrust"))
        if expected_fingerprint and observed_fingerprint != expected_fingerprint and not retrust:
            raise EnvironmentError(
                "服务器身份发生变化，请确认当前实例后重新建立信任",
                "E-SSH-FINGERPRINT",
                {"target_id": existing["target_id"], "can_retrust": True},
            )
        session.verify_fingerprint(observed_fingerprint, confirmed=True)
        fingerprint = observed_fingerprint
        result = EnvironmentScanner(
            session,
            data_path=payload.get("data_path") or "/root/autodl-tmp",
            comfy_path=payload.get("comfy_path") or "/root/ComfyUI",
            host_fingerprint=fingerprint,
            platform_hint=payload.get("platform") or "",
        ).scan()
        if existing:
            target_id = existing["target_id"]
            self.store.update_environment_target_fingerprint(target_id, fingerprint)
        else:
            target_id = self.store.create_environment_target(
                platform=payload.get("platform") or "unknown",
                host=connection.host,
                username=connection.username,
                port=connection.port,
                credential_ref=f"session-{uuid.uuid4().hex[:12]}",
                fingerprint=fingerprint,
                metadata={
                    "data_path": payload.get("data_path") or "/root/autodl-tmp",
                    "comfy_path": payload.get("comfy_path") or "/root/ComfyUI",
                },
            )
        scan_data = result.to_dict()
        scan_id = self.store.save_environment_scan(target_id, scan_data, result.raw_summary)
        public_scan = _strip_fingerprint_fields(scan_data)
        with self._lock:
            self._sessions[target_id] = session
        return {"target_id": target_id, "scan_id": scan_id, "scan": public_scan}

    def make_plan(self, target_id, scan_id, recipe_id="minimax-h3-sdxl"):
        recipe = load_recipe(recipe_id)
        scan_row = self.store.get_environment_scan(scan_id)
        if not scan_row or scan_row.get("target_id") != target_id:
            raise EnvironmentError("扫描快照不存在或不属于目标环境", "E-VERIFY")
        plan = build_plan(scan_row.get("summary") or {}, recipe)
        plan_id = self.store.save_deployment_plan(
            target_id, scan_id, recipe_id, recipe["version"],
            dataclasses.asdict(plan.estimate) | {"status": plan.status},
            diff={"mode": plan.mode, "items": plan.differences},
            risks=plan.risks,
            status=plan.status,
        )
        plan_payload = plan.to_dict()
        plan_payload.update({"plan_id": plan_id, "target_id": target_id, "scan_id": scan_id, "recipe_id": recipe_id, "recipe_version": recipe["version"]})
        with self._lock:
            self._plans[plan_id] = {"plan": plan_payload, "recipe": recipe, "scan": scan_row.get("summary") or {}}
        return plan_payload

    def start_deploy(self, plan_id, recipe_version, confirm=False):
        if not confirm:
            raise EnvironmentError("部署前必须确认可能产生磁盘、流量和 GPU 费用", "E-CONFIRMATION-REQUIRED")
        plan_info = self._load_plan(plan_id)
        if str(recipe_version or "") != str(plan_info["plan"]["recipe_version"]):
            raise EnvironmentError("recipe 版本与计划不一致，请重新生成计划", "E-WORKFLOW")
        job_id = plan_id
        with self._lock:
            existing = self._jobs.get(job_id)
            if existing and existing.get("status") in {"deploying", "verifying"}:
                return self._public_job(existing)
            session = self._sessions.get(plan_info["plan"]["target_id"])
            if self.downloader_factory:
                downloader = self.downloader_factory()
            elif session is not None:
                scan = plan_info.get("scan") or {}
                disk = scan.get("disk") or {}
                comfy = scan.get("comfyui") or {}
                downloader = RemoteDownloader(
                    session,
                    disk.get("path") or "/root/autodl-tmp",
                    comfy.get("path") or "/root/ComfyUI",
                )
            else:
                raise EnvironmentError("SSH 会话已失效，请重新扫描远端环境", "E-SSH-AUTH")
            deployer = EnvironmentDeployer(
                session=session,
                downloader=downloader,
                store=self.store,
                progress_callback=lambda result, job_id=job_id: self._update_job_progress(job_id, result),
            )
            self._deployers[job_id] = deployer
            job = {"job_id": job_id, "status": "deploying", "plan_id": plan_id, "result": None}
            self._jobs[job_id] = job
            thread = threading.Thread(target=self._run_deploy, args=(job_id, deployer, plan_info), daemon=True)
            job["thread"] = thread
            thread.start()
        return self._public_job(job)

    def get_job(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                return self._public_job(job)
        stored = self.store.get_environment_job(job_id)
        return {"job_id": job_id, "status": "unknown", "stored": stored} if stored else None

    def retry_step(self, job_id, step_name):
        with self._lock:
            deployer = self._deployers.get(job_id)
        if not deployer:
            raise EnvironmentError("部署任务不在当前控制台会话中", "E-VERIFY")
        try:
            result = deployer.retry_step(step_name)
        except Exception:
            # Keep a failed retry visible to the next poll even though the API
            # still returns the stable error code to the caller.
            current = getattr(deployer, "_last_job", None)
            if current is not None:
                with self._lock:
                    self._jobs[job_id]["status"] = current.status
                    self._jobs[job_id]["result"] = current.to_dict()
            raise
        with self._lock:
            self._jobs[job_id]["status"] = result.status
            self._jobs[job_id]["result"] = result.to_dict()
        return self.get_job(job_id)

    def cancel_job(self, job_id):
        with self._lock:
            deployer = self._deployers.get(job_id)
        if not deployer:
            raise EnvironmentError("部署任务不存在", "E-VERIFY")
        deployer.cancel()
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = "interrupted"
        return self.get_job(job_id)

    def list_recipes(self):
        recipe_dir = Path(__file__).resolve().parents[1] / "recipes"
        items = []
        for path in sorted(recipe_dir.glob("*.json")):
            try:
                recipe = load_recipe(path.stem)
            except Exception as exc:
                items.append({"id": path.stem, "error": redact_environment_data(exc)})
                continue
            items.append({"id": recipe["id"], "version": recipe["version"], "platforms": recipe["platforms"], "requirements": recipe["requirements"]})
        return items

    def get_manifest(self, target_id):
        row = self.store.get_environment_manifest(target_id)
        return row.get("manifest") if row else None

    @staticmethod
    def redact_payload(value):
        secret_keys = {"password", "private_key", "api_key", "token", "credential"}
        if isinstance(value, dict):
            return {
                key: "***" if key.lower() in secret_keys else EnvironmentManager.redact_payload(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [EnvironmentManager.redact_payload(item) for item in value]
        return redact_environment_data(value)

    def _load_plan(self, plan_id):
        with self._lock:
            cached = self._plans.get(plan_id)
        if cached:
            return cached
        row = self.store.get_deployment_plan(plan_id)
        if not row:
            raise EnvironmentError("部署计划不存在", "E-WORKFLOW")
        recipe = load_recipe(row["recipe_id"])
        scan = self.store.get_environment_scan(row["scan_id"])
        runtime = build_plan(scan.get("summary") or {}, recipe)
        payload = runtime.to_dict()
        payload.update({"plan_id": plan_id, "target_id": row["target_id"], "scan_id": row["scan_id"], "recipe_id": row["recipe_id"], "recipe_version": row["recipe_version"]})
        cached = {"plan": payload, "recipe": recipe, "scan": scan.get("summary") or {}}
        with self._lock:
            self._plans[plan_id] = cached
        return cached

    def _run_deploy(self, job_id, deployer, plan_info):
        try:
            result = deployer.run(plan_info["plan"], has_gpu=bool((plan_info.get("scan") or {}).get("has_gpu")))
            payload = result.to_dict()
            with self._lock:
                self._jobs[job_id]["status"] = result.status
                self._jobs[job_id]["result"] = payload
            self.store.save_environment_manifest(plan_info["plan"]["target_id"], {
                "recipe_id": plan_info["plan"]["recipe_id"],
                "recipe_version": plan_info["plan"]["recipe_version"],
                "status": result.status,
                "completed_steps": result.completed_steps,
            })
        except Exception as exc:
            with self._lock:
                self._jobs[job_id]["status"] = "failed"
                self._jobs[job_id]["result"] = {"status": "failed", "error": redact_environment_data(exc)}

    def _update_job_progress(self, job_id, result):
        payload = result.to_dict() if hasattr(result, "to_dict") else dict(result or {})
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = payload.get("status") or job.get("status") or "deploying"
            job["result"] = payload

    @staticmethod
    def _public_job(job):
        return EnvironmentManager.redact_payload({key: value for key, value in job.items() if key not in {"thread"}})
