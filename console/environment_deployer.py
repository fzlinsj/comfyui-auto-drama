"""Resumable deployment state machine with an explicit GPU verification gate."""

from __future__ import annotations

import dataclasses
import os
import time

try:
    from .environment_models import EnvironmentError, environment_status_after_prepare, redact_environment_data
    from .environment_downloader import ResumableDownloader
except ImportError:
    from environment_models import EnvironmentError, environment_status_after_prepare, redact_environment_data
    from environment_downloader import ResumableDownloader


CPU_STEPS = [
    "scan", "prepare_dirs", "create_venv", "install_comfyui", "install_nodes",
    "download_models", "configure_shared_models", "copy_workflows", "manifest",
]
GPU_STEPS = ["verify_sdxl", "verify_t2v", "verify_i2v", "verify_r2v"]
SERVICES = {step.removeprefix("verify_"): step for step in GPU_STEPS}


@dataclasses.dataclass
class DeploymentJob:
    status: str
    active_step: str = ""
    completed_steps: list[str] = dataclasses.field(default_factory=list)
    deferred_steps: list[str] = dataclasses.field(default_factory=list)
    failed_steps: list[str] = dataclasses.field(default_factory=list)
    messages: list[str] = dataclasses.field(default_factory=list)
    plan_id: str = ""

    def to_dict(self):
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class VerificationResult:
    status: str
    results: dict
    failed_services: list[str]
    message: str = ""

    def to_dict(self):
        return dataclasses.asdict(self)


class EnvironmentDeployer:
    def __init__(self, session=None, downloader=None, store=None, verifier=None, progress_callback=None):
        self.session = session
        self.downloader = downloader or ResumableDownloader()
        self.store = store
        self.verifier = verifier
        self.progress_callback = progress_callback
        self._verified_downloads = set()
        self._step_status = {}
        self._last_plan = None
        self._last_job = None
        self._cancelled = False

    def run(self, plan, has_gpu=False, cancel=None):
        self._last_plan = plan
        plan_data = plan.to_dict() if hasattr(plan, "to_dict") else dict(plan or {})
        plan_id = str(plan_data.get("plan_id") or plan_data.get("id") or "")
        job = DeploymentJob("deploying", plan_id=plan_id)
        if plan_data.get("status") == "blocked":
            job.status = "blocked"
            job.messages.append("部署计划被阻止")
            return self._finish(job)
        self._cancelled = False
        for step in CPU_STEPS:
            job.active_step = step
            self._notify(job)
            if cancel and cancel():
                self._cancelled = True
            if self._cancelled:
                self._record(job, step, "interrupted", "部署已取消")
                self._notify(job)
                job.status = "interrupted"
                return self._finish(job)
            if self._step_status.get(step) == "succeeded":
                job.completed_steps.append(step)
                continue
            try:
                self._execute_cpu_step(step, plan_data, cancel)
                self._step_status[step] = "succeeded"
                self._record(job, step, "succeeded")
                job.completed_steps.append(step)
                self._notify(job)
            except Exception as exc:
                self._step_status[step] = "failed"
                self._record(job, step, "failed", self._describe_error(exc))
                job.failed_steps.append(step)
                job.status = "failed"
                self._notify(job)
                return self._finish(job)
        if not has_gpu:
            job.active_step = ""
            job.deferred_steps = list(GPU_STEPS)
            job.status = environment_status_after_prepare(False)
            self._notify(job)
            return self._finish(job)
        verification = plan_data.get("verification") or {}
        for step in GPU_STEPS:
            job.active_step = step
            self._notify(job)
            if self._step_status.get(step) == "succeeded":
                job.completed_steps.append(step)
                continue
            service = step.removeprefix("verify_")
            try:
                result = self._verify(service, plan_data, verification)
                if not self._verification_ok(result):
                    raise EnvironmentError(f"{service} 验证失败", "E-VERIFY", {"service": service})
                self._step_status[step] = "succeeded"
                self._record(job, step, "succeeded", result)
                job.completed_steps.append(step)
                self._notify(job)
            except Exception as exc:
                self._step_status[step] = "failed"
                self._record(job, step, "failed", redact_environment_data(exc))
                job.failed_steps.append(step)
                self._notify(job)
        job.status = "available" if not job.failed_steps else "failed"
        job.active_step = ""
        return self._finish(job)

    def retry_step(self, step_name, cancel=None):
        if step_name not in CPU_STEPS + GPU_STEPS:
            raise ValueError(f"unknown deployment step: {step_name}")
        if not self._last_plan:
            raise ValueError("no deployment plan")
        job = self._last_job or DeploymentJob("deploying")
        if self._step_status.get(step_name) == "succeeded":
            return job
        plan_data = self._last_plan.to_dict() if hasattr(self._last_plan, "to_dict") else dict(self._last_plan)
        try:
            details = None
            if step_name.startswith("verify_"):
                service = step_name.removeprefix("verify_")
                details = self._verify(service, plan_data, plan_data.get("verification") or {})
                if not self._verification_ok(details):
                    raise EnvironmentError(f"{service} 验证失败", "E-VERIFY")
            else:
                self._execute_cpu_step(step_name, plan_data, cancel)
            self._step_status[step_name] = "succeeded"
            self._record(job, step_name, "succeeded", details)
        except Exception as exc:
            self._step_status[step_name] = "failed"
            self._record(job, step_name, "failed", self._describe_error(exc))
            self._sync_job(job)
            self._finish(job)
            raise
        self._sync_job(job)
        job.active_step = ""
        self._notify(job)
        return self._finish(job)

    def finalize_verification(self, results):
        results = dict(results or {})
        failed = [service for service in SERVICES if not self._verification_ok(results.get(service))]
        status = "available" if not failed else "failed"
        return VerificationResult(status, results, failed, "" if not failed else "验证未全部通过")

    def cancel(self):
        self._cancelled = True
        if self._last_job and self._last_job.status in {"deploying", "verifying"}:
            self._last_job.status = "interrupted"
        return self._last_job

    def _execute_cpu_step(self, step, plan, cancel):
        if step == "download_models":
            for resource in plan.get("download_tasks") or []:
                filename = str(resource.get("filename") or "")
                if filename in self._verified_downloads:
                    continue
                result = self.downloader.download(resource, cancel=cancel)
                if getattr(result, "status", "") not in {"downloaded", "reused"}:
                    raise EnvironmentError(f"资源下载失败: {filename}", "E-DOWNLOAD")
                self._verified_downloads.add(filename)
            return
        if step == "scan" and self.session is not None and hasattr(self.session, "fingerprint_confirmed"):
            if not self.session.fingerprint_confirmed:
                raise EnvironmentError("SSH 指纹尚未确认", "E-SSH-FINGERPRINT")
        # The concrete remote install commands are intentionally delegated to a future recipe adapter.
        # Keeping these steps explicit makes progress resumable without mutating an existing bundle.

    def _verify(self, service, plan, verification):
        if self.verifier:
            return self.verifier(service, plan)
        return verification.get(service, False)

    @staticmethod
    def _verification_ok(value):
        if isinstance(value, dict):
            return bool(value.get("success") or value.get("ok"))
        return bool(value)

    def _record(self, job, step, status, details=None):
        if self.store and job.plan_id:
            self.store.upsert_deployment_step(job.plan_id, step, status, {"message": details} if details else {})
        if details:
            job.messages.append(f"{step}: {details}")

    @staticmethod
    def _describe_error(exc):
        message = redact_environment_data(exc)
        details = getattr(exc, "details", {}) or {}
        sources = details.get("sources") if isinstance(details, dict) else None
        if sources:
            message = f"{message}；" + "；".join(redact_environment_data(item) for item in sources)
        return message

    def _finish(self, job):
        self._last_job = job
        self._notify(job)
        return job

    def _notify(self, job):
        if not self.progress_callback:
            return
        try:
            self.progress_callback(job)
        except Exception:
            # Progress reporting must never turn a completed deployment step
            # into a deployment failure.
            pass

    def _sync_job(self, job):
        """Rebuild visible step lists after a manual retry without rerunning other steps."""
        ordered = CPU_STEPS + GPU_STEPS
        job.completed_steps = [step for step in ordered if self._step_status.get(step) == "succeeded"]
        job.failed_steps = [step for step in ordered if self._step_status.get(step) == "failed"]
        job.deferred_steps = [
            step for step in GPU_STEPS
            if self._step_status.get(step) not in {"succeeded", "failed"}
        ]
        if job.failed_steps:
            job.status = "failed"
        elif len(job.completed_steps) == len(ordered):
            job.status = "available"
        elif any(self._step_status.get(step) == "succeeded" for step in GPU_STEPS):
            job.status = "verifying"
        elif all(self._step_status.get(step) == "succeeded" for step in CPU_STEPS):
            job.status = "prepared_waiting_gpu"
        else:
            job.status = "deploying"
