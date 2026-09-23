# AutoDL MiniMax H3 Model Compatibility Implementation Plan

> **For agentic workers:** Execute inline in this session; do not delegate.

**Goal:** Align T2V, I2V, and R2V graph model names with the weights exposed by the user's AutoDL ComfyUI.

**Architecture:** Keep model selection in existing workflow graph construction and template files. Add focused unit tests against generated graphs, preserve the existing R2V UNet/CLIP configuration, and document the compatibility behavior in the required changelog.

**Tech Stack:** Python standard library, unittest, ComfyUI `/object_info` model metadata.

---

### Task 1: Regression coverage

**Files:**
- Create: `console/tests/test_autodl_model_compat.py`
- Test: `workflows/build_api_graphs.py`, `workflows/minimax_h3_t2v_turbo.json`, `workflows/i2v_api_template.json`

- [x] Assert T2V and R2V graph nodes choose `minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors`.
- [x] Assert I2V's CLIP loader chooses `qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors`.
- [x] Assert R2V retains configured official Ref2VA UNet and NVFP4 AWQ CLIP.
- [x] Run `python -m unittest console.tests.test_autodl_model_compat -v`; all three failed on the existing mismatched filenames as expected.

### Task 2: Workflow compatibility

**Files:**
- Modify: `workflows/build_api_graphs.py`
- Modify: `workflows/minimax_h3_t2v_turbo.json`
- Modify: `workflows/i2v_api_template.json`
- Modify: `console/CHANGELOG.md`

- [x] Update the R2V Turbo LoRA constant and T2V/I2V template Turbo LoRA values to the installed pruned ComfyUI LoRA.
- [x] Update I2V CLIP widget value to the installed H3 Heretic NVFP4 encoder.
- [x] Add a top changelog entry with scope, exact verification commands, and operational impact.
- [x] Run the focused test, full `unittest` discovery, Python compile check, JSON parse checks, and `git diff --check`; all passed (3 focused tests, 12 total).

Runtime restart is pending because the current local chain-daemon log reports ten waiting tasks. Do not stop the daemon without confirming the user's desired handling of those persisted tasks.

Do not submit a ComfyUI generation job or change/download server files during implementation.
