import unittest
from html.parser import HTMLParser
from pathlib import Path


INDEX = Path(__file__).resolve().parents[1] / "index.html"


class _HierarchyParser(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.stack = []
        self.ancestors_by_id = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        node = {"tag": tag, "id": attributes.get("id"), "classes": set(attributes.get("class", "").split())}
        if node["id"]:
            self.ancestors_by_id[node["id"]] = [*self.stack, node]
        if tag not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                return


class SettingsDiagnosticsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = INDEX.read_text(encoding="utf-8")

    def test_generation_diagnostics_live_in_settings(self):
        for service in ("image", "comfyui_t2v", "comfyui_i2v", "comfyui_r2v"):
            self.assertIn(f'data-diagnostic="{service}"', self.source)
        self.assertIn("collectConfigFromForm", self.source)

    def test_image_generation_has_one_provider_aware_real_test_entry(self):
        self.assertNotIn('data-diagnostic="comfyui_image"', self.source)
        self.assertEqual(
            self.source.count('data-diagnostic="image" data-diagnostic-action="real"'),
            1,
        )
        server_section = self.source.split('id="serverInput"', 1)[1].split('<div class="cfg-block">', 1)[0]
        self.assertIn("ComfyUI 连接", server_section)
        self.assertNotIn("测试生图", server_section)
        self.assertNotIn('id="btnCheck"', server_section)
        self.assertNotIn('id="connInfo"', server_section)

    def test_inline_diagnostic_results_use_named_hint_containers(self):
        inline = self.source.split("async function runInlineDiagnostic(button) {", 1)[1].split("document.querySelectorAll('[data-diagnostic]')", 1)[0]
        self.assertIn("button.dataset.diagnosticTarget", inline)
        self.assertIn("button.closest('.diag-inline')?.querySelector('.hint')", inline)
        self.assertNotIn("button.nextElementSibling", inline)
        self.assertIn("needs_real_test: '需要真实测试'", inline)
        self.assertIn('data-diagnostic="image" data-diagnostic-action="quick" data-diagnostic-target="diagImage"', self.source)
        self.assertIn('data-diagnostic="image" data-diagnostic-action="real" data-diagnostic-target="diagImage"', self.source)
        self.assertIn('data-diagnostic="comfyui_r2v" data-diagnostic-action="real" data-diagnostic-target="diagComfyuiVideo"', self.source)
        self.assertIn('data-diagnostic="comfyui_r2v" data-diagnostic-action="real" data-diagnostic-target="diagR2v"', self.source)

    def test_image_diagnostic_accepts_a_prompt_and_renders_preview(self):
        for element_id in ("imgDiagnosticPrompt", "diagImagePreview", "diagImageOutput", "diagImageLink", "diagImageMeta"):
            self.assertIn(f'id="{element_id}"', self.source)
        inline = self.source.split("async function runInlineDiagnostic(button) {", 1)[1].split("document.querySelectorAll('[data-diagnostic]')", 1)[0]
        self.assertIn("prompt: imagePrompt", inline)
        self.assertIn("renderDiagnosticImagePreview", inline)
        preview = self.source.split("function renderDiagnosticImagePreview", 1)[1].split("async function runInlineDiagnostic", 1)[0]
        self.assertIn("result.url", preview)
        self.assertIn("'/media/'", preview)
        self.assertIn("encodeURIComponent", preview)

    def test_diagnostic_errors_accept_non_json_responses(self):
        self.assertIn("const raw = await r.text()", self.source)
        self.assertIn("JSON.parse(raw)", self.source)

    def test_diagnostic_route_404_explains_that_backend_needs_restart(self):
        self.assertIn("r.status === 404", self.source)
        self.assertIn("请重启控制台服务", self.source)

    def test_inline_real_diagnostic_polls_until_terminal_result(self):
        inline = self.source.split("async function runInlineDiagnostic(button) {", 1)[1].split("document.querySelectorAll('[data-diagnostic]')", 1)[0]
        self.assertIn("/api/diagnostics/run?run_id=", inline)
        self.assertIn("x.status === 'running'", inline)
        self.assertIn("x.result?.filename", inline)
        self.assertIn("x.failure?.summary", inline)
        self.assertIn("setTimeout(poll, 1500)", inline)

    def test_llm_chat_panel_uses_interactive_chat_route(self):
        self.assertIn('id="llmChatPanel"', self.source)
        self.assertIn("/api/llm/chat", self.source)
        self.assertIn("llmChatHistory", self.source)
        self.assertIn("btnLlmChatSend", self.source)
        self.assertIn("btnLlmChatClose", self.source)

    def test_quick_llm_check_shows_check_and_error_details(self):
        self.assertIn("d.details?.error", self.source)
        self.assertIn("d.details?.check", self.source)

    def test_step_seven_diagnostic_card_is_not_visible(self):
        self.assertIn('id="diagnosticsCard" style="display:none;', self.source)

    def test_image_provider_and_model_selection_are_explicit(self):
        for provider in ('comfyui', 'cloud', 'local'):
            self.assertIn(f'<option value="{provider}"', self.source)
        for model in ('gpt-image-1', 'gpt-image-1-mini', 'agnes-image-2.5-flash'):
            self.assertIn(f'value="{model}"', self.source)
        self.assertIn('selectedImageModel()', self.source)
        self.assertIn('diagComfyuiVideo', self.source)

    def test_provider_specific_settings_are_grouped_and_aligned(self):
        for element_id in ('llmProviderTypeRow', 'llmCloudBox', 'llmLocalBox', 'imgProviderTypeRow', 'imgCloudBox', 'imgLocalBox', 'imgComfyuiBox'):
            self.assertIn(f'id="{element_id}"', self.source)
        self.assertIn('setting-choice', self.source)
        self.assertIn('white-space: nowrap', self.source)
        self.assertIn("$('imgComfyuiBox').style.display", self.source.replace(' ', ''))
        self.assertIn("$('llmLocalBox').style.display", self.source.replace(' ', ''))

    def test_settings_drawer_is_wide_and_keeps_endpoint_next_to_key(self):
        self.assertIn("width: min(720px, calc(100vw - 24px))", self.source)
        llm = self.source.split('id="llmCloudBox"', 1)[1].split('</div>\n      <div id="llmLocalBox"', 1)[0]
        image = self.source.split('id="imgCloudBox"', 1)[1].split('</div>\n      </div>\n      <div id="imgLocalBox"', 1)[0]
        self.assertLess(llm.index('id="llmCloudUrl"'), llm.index('id="llmCloudKey"'))
        self.assertLess(llm.index('id="llmCloudKey"'), llm.index('id="llmCloudModel"'))
        self.assertLess(image.index('id="imgCloudUrl"'), image.index('id="imgCloudKey"'))
        self.assertLess(image.index('id="imgCloudKey"'), image.index('id="imgCloudModelSelect"'))

    def test_all_settings_content_stays_inside_the_shared_scroll_container(self):
        parser = _HierarchyParser()
        parser.feed(self.source)

        for element_id in ("r2vUnet", "lmToken", "btnSaveConfig", "btnEditRules"):
            ancestors = parser.ancestors_by_id[element_id]
            self.assertTrue(
                any("d-body" in node["classes"] for node in ancestors),
                f"{element_id} escaped the settings drawer scroll container",
            )

    def test_comfyui_is_not_a_cloud_interface_format(self):
        image_format = self.source.split('id="imgProviderType"', 1)[1].split('</select>', 1)[0]
        self.assertNotIn('<option value="comfyui">ComfyUI 工作流</option>', image_format)
        self.assertIn("if (type === 'comfyui') $('imgProvider').value = 'comfyui'", self.source)


if __name__ == "__main__":
    unittest.main()
