# ComfyUI Diagnostics And Deployment Verification Fix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make diagnostic images resolve through `/media/` and make environment deployment verify SDXL/T2V/I2V/R2V against the configured ComfyUI server instead of failing by default.

**Architecture:** Keep path ownership in `batch_console.py`, which already resolves project-relative storage paths, and inject that absolute directory into `ServiceDiagnostics`. Add a focused callable verifier that builds the four existing production workflow graphs, runs `ComfyUIClient.preflight()`, and retries with known compatible H3 filename variants exposed by ComfyUI. Inject the verifier into `EnvironmentManager`, which forwards it to `EnvironmentDeployer`.

**Tech Stack:** Python 3.13, unittest, existing ComfyUI HTTP client and workflow builders.

---

### Task 1: Lock In The Regressions

**Files:**
- Create: `console/tests/test_batch_console_factories.py`
- Create: `console/tests/test_environment_verifier.py`
- Modify: `console/tests/test_environment_api.py`

- [x] Add a factory test proving diagnostics receives `OUTPUTS_DIR`.
- [x] Add verifier tests proving all four workflow graphs call preflight and H3 variants are substituted only from ComfyUI's advertised options.
- [x] Add a manager test proving the configured verifier is passed into `EnvironmentDeployer`.
- [x] Run the focused tests and confirm they fail for the missing behavior.

### Task 2: Implement The Minimal Fix

**Files:**
- Create: `console/environment_verifier.py`
- Modify: `console/environment_manager.py`
- Modify: `console/batch_console.py`

- [x] Implement the callable workflow verifier using existing graph builders and `ComfyUIClient.preflight()`.
- [x] Add constrained MiniMax H3/Qwen compatible-filename selection, including the existing Ref2VA-to-FL2VA fallback.
- [x] Inject the verifier through `EnvironmentManager` into each `EnvironmentDeployer`.
- [x] Pass the already resolved absolute `OUTPUTS_DIR` into `ServiceDiagnostics`.
- [x] Run focused tests until green.

### Task 3: Document And Verify

**Files:**
- Modify: `console/CHANGELOG.md`

- [x] Add `2026-09-27 - v0.13.64` at the top with behavior, verification, and impact notes.
- [x] Run the full console test suite with Python 3.13.15.
- [x] Run `py_compile` for changed Python modules.
- [x] Run a safe whitespace/conflict-marker scan; Git inspection was blocked by repository ownership policy.
