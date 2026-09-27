# 真人漫剧生图修正 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** 修正 ComfyUI 资产生图，使真人角色、真实动物和现实场景使用正确提示词，并在 checkpoint 未配置或不可用时阻止错误任务提交。

**Architecture:** 保留现有标准 SDXL 工作流和资产接口。前端在 `console/index.html` 中进行角色类型识别、类型选择和模板生成；后端在 `console/batch_console.py` 中统一添加现实摄影负面约束并校验 ComfyUI checkpoint。`workflows/build_sdxl_graph.py` 继续负责纯工作流组装，不承担配置兜底校验，以免破坏环境诊断工作流。

**Tech Stack:** Python 3.13、标准库 `unittest`、ComfyUI `/object_info` 预检、现有单页 HTML/JavaScript。

---

### Task 1: Add failing regression tests for role prompt policy

**Files:**
- Create: `console/tests/test_realistic_drama_prompts.py`
- Test: `console/index.html`

- [ ] **Step 1: Write the failing tests**

Create tests that read the inline script from `console/index.html` and assert the intended observable policy:

```python
import unittest
from pathlib import Path


HTML = Path(__file__).resolve().parents[1] / "index.html"


class RealisticDramaPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = HTML.read_text(encoding="utf-8")

    def test_role_type_classifier_includes_real_animals(self):
        self.assertIn("function inferRoleType", self.source)
        self.assertIn("公鸡", self.source)
        self.assertIn("animal", self.source)

    def test_role_prompt_has_separate_animal_template(self):
        self.assertIn("真实动物摄影", self.source)
        self.assertIn("不得出现人脸或人体", self.source)

    def test_role_prompt_removes_ambiguous_gender_fallback(self):
        self.assertNotIn("根据名字与描述判断性别", self.source)
        self.assertNotIn("gender according to the description", self.source)

    def test_story_prompt_does_not_require_human_limbs_for_animals(self):
        self.assertIn("动物保持真实物种", self.source)
        self.assertNotIn("每人四肢完整各两只手", self.source)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m unittest console.tests.test_realistic_drama_prompts -v
```

Expected: FAIL because the current HTML has no `inferRoleType`, still contains the ambiguous fallback, and applies human-limb constraints globally.

### Task 2: Implement realistic human/animal role templates

**Files:**
- Modify: `console/index.html:2770-3195`

- [ ] **Step 1: Add role type classification and backward-compatible selection**

Implement `inferRoleType(desc)` with explicit animal keywords including `公鸡`, `鸡`, `狗`, `猫`, `牛`, `马`, `羊`, `猪`, `鸟`, `狐狸`, `狼`, `鱼`, and human gender keywords. Return `animal`, `human_male`, `human_female`, or `unknown`. Read the new `assetImgs.roleType[name]` first and map legacy `roleGender[name]` values to human types when no new type exists. Replace the gender-only select with a role-type select offering 真人男性、真人女性、真实动物、未确定.

- [ ] **Step 2: Replace `defaultRolePrompt` with type-specific templates**

Keep the existing era, role description, hair and costume fields for humans. The human template must include `真实演员`, `电影剧照`, `自然光`, `真实皮肤与服装材质`. The animal template must include `真实动物摄影`, the role description and `不得出现人脸或人体、不得穿人类服装、不得拟人化`. The unknown template must use a neutral real-world subject description and never add a gender guess.

Append one shared negative phrase containing `文字、字幕、logo、水印、书法、古画、插画、二次元、卡通、3D渲染、拼接、重复主体、额外人物、畸形肢体`.

- [ ] **Step 3: Update view and story prompts**

Make `roleViewPrompt` emit animal-specific front/face/side/back photography language for `animal`; keep face, side and back human language only for human types. Update `defaultStoryPrompt` role constraints so animal roles are described as real species and the prompt says `动物保持真实物种，不拟人化`; remove the unconditional human-hand/limb requirement. Preserve exact costume and hair text for human roles.

- [ ] **Step 4: Pass role type to asset verification and preserve custom prompts**

In `genAsset`, send `expected.role_type` and keep `assetPrompts.role[name]` as the submitted prompt. When a user has edited a prompt, changing the select only updates the default textarea value; it must not overwrite a saved custom prompt in project state until the user submits the edited value.

- [ ] **Step 5: Run the regression tests**

Run:

```powershell
python -m unittest console.tests.test_realistic_drama_prompts -v
```

Expected: PASS.

### Task 3: Add failing backend tests for ComfyUI prompt safety and checkpoint validation

**Files:**
- Modify: `console/tests/test_batch_console_factories.py`
- Test: `console/batch_console.py`

- [ ] **Step 1: Add tests for negative prompt merging and checkpoint errors**

Add tests that call the backend helpers without a live ComfyUI server:

```python
class ImageGenerationPolicyTests(unittest.TestCase):
    def test_comfyui_endpoint_does_not_silently_fill_checkpoint(self):
        with patch.object(batch_console, "_CONFIG", {
            "comfyui": {"server": "http://127.0.0.1:6006"},
            "image_gen": {"provider": "comfyui", "comfyui": {"checkpoint": ""}},
        }):
            endpoint, backup = batch_console._image_gen_endpoints()
        self.assertIsNone(backup)
        self.assertEqual(endpoint["model"], "")

    def test_comfyui_negative_prompt_contains_realistic_exclusions(self):
        result = batch_console._merge_negative_prompt("text, watermark")
        self.assertIn("text", result)
        self.assertIn("古画", result)
        self.assertIn("3D", result)

    def test_missing_checkpoint_has_actionable_error(self):
        with self.assertRaisesRegex(RuntimeError, "image_gen.comfyui.checkpoint"):
            batch_console._validate_comfyui_checkpoint({"model": ""})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```powershell
python -m unittest console.tests.test_batch_console_factories.ImageGenerationPolicyTests -v
```

Expected: FAIL because `_merge_negative_prompt` and `_validate_comfyui_checkpoint` do not exist and the endpoint currently returns the SDXL fallback checkpoint.

### Task 4: Implement backend safety and explicit checkpoint handling

**Files:**
- Modify: `console/batch_console.py:2951-3005`
- Modify: `console/tests/test_batch_console_factories.py`

- [ ] **Step 1: Add a shared ComfyUI negative prompt and checkpoint helpers**

Define a module constant for the realistic-drama negative terms and implement:

```python
def _merge_negative_prompt(value):
    parts = [str(value or "").strip(), REALISTIC_DRAMA_NEGATIVE_PROMPT]
    return ", ".join(dict.fromkeys(part for part in parts if part))


def _validate_comfyui_checkpoint(endpoint):
    checkpoint = str((endpoint or {}).get("model") or "").strip()
    if not checkpoint:
        raise RuntimeError(
            "ComfyUI checkpoint 未配置，请在 config.json 的 "
            "image_gen.comfyui.checkpoint 中填写实际模型文件名"
        )
    return checkpoint
```

- [ ] **Step 2: Remove silent checkpoint fallback from `_image_gen_endpoints`**

Return the configured checkpoint string, including an empty string, instead of `sd_xl_base_1.0.safetensors`. Keep `build_sdxl_graph`'s internal fallback untouched for environment diagnostics that intentionally build a generic graph.

- [ ] **Step 3: Validate and merge before submitting an image task**

In `_img_comfyui`, call `_validate_comfyui_checkpoint(ep)` before building the graph, pass the returned value as `checkpoint`, and pass `_merge_negative_prompt(ep.get("negative_prompt"))` as `negative_prompt`. Keep the existing `client.preflight(graph)` call; its `missing_models` result handles a configured-but-unavailable filename and must be included in the raised error.

- [ ] **Step 4: Make asset verification aware of animals**

Read `expected.role_type` in `verify_asset`. For `animal`, ask the vision verifier to check the named real species, prohibit human faces/bodies/clothing and keep natural anatomy; do not issue a human gender check. For human types, retain the existing gender/look checks. Update re-verification to pass the stored role type when available and preserve legacy gender fallback.

- [ ] **Step 5: Run focused backend tests**

Run:

```powershell
python -m unittest console.tests.test_batch_console_factories.ImageGenerationPolicyTests -v
python -m unittest console.tests.test_sdxl_graph -v
```

Expected: PASS, with no live network call.

### Task 5: Update changelog and run full verification

**Files:**
- Modify: `console/CHANGELOG.md` (add a new entry at the top)

- [ ] **Step 1: Add the required changelog entry**

Add a dated entry describing the realistic human/animal prompt split, explicit checkpoint validation, negative prompt safety, tests run, and the fact that existing historical images are unchanged.

- [ ] **Step 2: Run the complete verification suite**

Run:

```powershell
python -m unittest discover -s console/tests -p "test_*.py"
python -m py_compile console/batch_console.py console/environment_verifier.py workflows/build_sdxl_graph.py
git diff --check
```

Expected: all tests pass, compilation exits with code 0, and `git diff --check` reports no whitespace errors.

- [ ] **Step 3: Perform a live configuration preflight when ComfyUI is reachable**

With the user's SSH tunnel at `http://127.0.0.1:6006`, set a real checkpoint filename in `config.json`, restart the console, and verify that the diagnostic log shows that checkpoint and the configured sampler/steps/CFG. If the tunnel is unavailable, report that live image generation remains unverified rather than claiming success.
