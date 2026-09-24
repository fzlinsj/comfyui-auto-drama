import unittest
from pathlib import Path


INDEX = Path(__file__).resolve().parents[1] / "index.html"


class SettingsDiagnosticsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = INDEX.read_text(encoding="utf-8")

    def test_generation_diagnostics_live_in_settings(self):
        for service in ("comfyui_image", "comfyui_t2v", "comfyui_i2v", "comfyui_r2v"):
            self.assertIn(f'data-diagnostic="{service}"', self.source)
        self.assertIn("collectConfigFromForm", self.source)

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

    def test_comfyui_is_not_a_cloud_interface_format(self):
        image_format = self.source.split('id="imgProviderType"', 1)[1].split('</select>', 1)[0]
        self.assertNotIn('<option value="comfyui">ComfyUI 工作流</option>', image_format)
        self.assertIn("if (type === 'comfyui') $('imgProvider').value = 'comfyui'", self.source)


if __name__ == "__main__":
    unittest.main()
