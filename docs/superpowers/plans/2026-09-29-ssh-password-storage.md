# SSH Password Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Add Windows DPAPI-backed, per-environment SSH password memory with server-side reuse and an explicit clear action, without exposing plaintext credentials to SQLite, browser storage, logs, Git, or API responses.

**Architecture:** A focused credential module owns DPAPI encryption and an atomic JSON ciphertext store under the current Windows user local-app-data directory. EnvironmentManager resolves an existing target before authentication, optionally loads its saved password, saves only after successful SSH authentication, and exposes non-secret status/clear methods consumed by two API routes and the existing deployment UI.

**Tech Stack:** Python 3.13 standard library, Windows DPAPI through ctypes, SQLite target metadata, HTTPServer routes, vanilla HTML/JavaScript, unittest.

---

## File Structure

- Create console/environment_credentials.py: DPAPI adapter, encrypted file store, atomic persistence, and safe unsupported-platform behavior.
- Create console/tests/test_environment_credentials.py: credential-store unit tests and Windows DPAPI round-trip test.
- Modify console/task_store.py: fetch a target by ID and update only credential_ref.
- Modify console/tests/test_environment_store.py: target credential-reference persistence tests and existing no-secret-column regression.
- Modify console/environment_manager.py: saved-password resolution, post-auth save, status, clear, and non-secret response flags.
- Modify console/tests/test_environment_api.py: manager behavior tests with an injected fake credential store.
- Modify console/batch_console.py: credential status and clear API routes.
- Modify console/tests/test_environment_api_routes.py: route registration and credential-response safety checks.
- Modify console/index.html: remember checkbox, saved-state label, clear button, status refresh, payload flag, and clear action.
- Modify console/tests/test_environment_ui.py: DOM, payload, endpoint, event-binding, and browser-storage security assertions.
- Modify console/CHANGELOG.md: required v0.13.92 entry with behavior, security boundary, and verification commands.

### Task 1: Build the DPAPI Credential Store

**Files:**
- Create: console/tests/test_environment_credentials.py
- Create: console/environment_credentials.py

- [ ] **Step 1: Write failing credential-store tests**

Create console/tests/test_environment_credentials.py with deterministic tests that never use a real SSH password:

~~~python
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

from environment_credentials import CredentialStoreError, EnvironmentCredentialStore


class ReversibleProtector:
    def protect(self, value):
        return b"cipher:" + bytes(value)[::-1]

    def unprotect(self, value):
        raw = bytes(value)
        if not raw.startswith(b"cipher:"):
            raise CredentialStoreError("invalid ciphertext")
        return raw[len(b"cipher:"):][::-1]


class EnvironmentCredentialStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "credentials.json"
        self.store = EnvironmentCredentialStore(
            path=self.path,
            protector=ReversibleProtector(),
            supported=True,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_round_trip_replace_and_delete(self):
        ref = self.store.save("first-secret")
        self.assertEqual(self.store.load(ref), "first-secret")
        self.assertEqual(self.store.save("second-secret", credential_ref=ref), ref)
        self.assertEqual(self.store.load(ref), "second-secret")
        self.assertTrue(self.store.delete(ref))
        self.assertIsNone(self.store.load(ref))
        self.assertFalse(self.store.delete(ref))

    def test_file_never_contains_plaintext(self):
        self.store.save("plain-secret-marker")
        rendered = self.path.read_text(encoding="utf-8")
        self.assertNotIn("plain-secret-marker", rendered)
        self.assertEqual(json.loads(rendered)["version"], 1)

    def test_corrupt_file_is_treated_as_missing(self):
        self.path.write_text("not-json", encoding="utf-8")
        self.assertIsNone(self.store.load("missing"))

    def test_unsupported_store_refuses_save_without_plaintext_fallback(self):
        store = EnvironmentCredentialStore(path=self.path, supported=False)
        with self.assertRaises(CredentialStoreError):
            store.save("must-not-be-written")
        self.assertFalse(self.path.exists())

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI only")
    def test_default_windows_dpapi_round_trip(self):
        store = EnvironmentCredentialStore(path=self.path)
        ref = store.save("dpapi-round-trip-marker")
        self.assertEqual(store.load(ref), "dpapi-round-trip-marker")
        self.assertNotIn("dpapi-round-trip-marker", self.path.read_text(encoding="utf-8"))
~~~

- [ ] **Step 2: Run the new tests and confirm the module is missing**

Run:

~~~powershell
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe' -m unittest console.tests.test_environment_credentials -v
~~~

Expected: FAIL with ModuleNotFoundError for environment_credentials.

- [ ] **Step 3: Implement the focused credential module**

Create console/environment_credentials.py. The public API and persistence shape must be exactly:

~~~python
class CredentialStoreError(RuntimeError):
    pass


class EnvironmentCredentialStore:
    def __init__(self, path=None, protector=None, supported=None):
        self.path = Path(path) if path else _default_store_path()
        self._supported = os.name == "nt" if supported is None else bool(supported)
        self.protector = protector or (_WindowsDpapiProtector() if self._supported else None)

    @property
    def supported(self):
        return bool(self._supported and self.protector)

    def save(self, password, credential_ref=None):
        if not self.supported:
            raise CredentialStoreError("当前系统不支持安全保存 SSH 密码")
        ref = str(credential_ref or uuid.uuid4().hex)
        payload = self._read_payload()
        ciphertext = self.protector.protect(str(password).encode("utf-8"))
        payload["credentials"][ref] = base64.b64encode(ciphertext).decode("ascii")
        self._write_payload(payload)
        return ref

    def load(self, credential_ref):
        if not self.supported or not credential_ref:
            return None
        encoded = self._read_payload()["credentials"].get(str(credential_ref))
        if not encoded:
            return None
        try:
            return self.protector.unprotect(base64.b64decode(encoded)).decode("utf-8")
        except Exception as exc:
            raise CredentialStoreError("已保存的 SSH 密码无法解密") from exc

    def delete(self, credential_ref):
        if not credential_ref:
            return False
        payload = self._read_payload()
        removed = payload["credentials"].pop(str(credential_ref), None) is not None
        if removed:
            self._write_payload(payload)
        return removed
~~~

Implement _default_store_path() as Path(os.environ["LOCALAPPDATA"]) / "ComfyUIAutoDrama" / "environment_credentials.json" when LOCALAPPDATA exists, with Path.home() / ".comfyui-auto-drama" as a path-only fallback. Never use the fallback to enable saving on a non-Windows platform.

Implement _read_payload() so missing, malformed, or wrong-version JSON returns {"version": 1, "credentials": {}}. Implement _write_payload() by creating the parent directory, writing UTF-8 JSON to a sibling temporary file, applying user read/write permissions, and replacing the destination with os.replace().

Implement _WindowsDpapiProtector with ctypes and CryptProtectData/CryptUnprotectData. Use CRYPTPROTECT_UI_FORBIDDEN, copy output bytes with ctypes.string_at(), and always release DPAPI output buffers using LocalFree(). Convert Windows failures to CredentialStoreError without including input data in the message.

- [ ] **Step 4: Run credential-store tests**

Run the Task 1 command again.

Expected: all tests PASS, including the DPAPI round-trip on this Windows 10 machine.

- [ ] **Step 5: Commit the credential module**

~~~powershell
git add -- console/environment_credentials.py console/tests/test_environment_credentials.py
git commit -m "feat: add DPAPI environment credential store"
~~~

### Task 2: Persist Only the Opaque Credential Reference

**Files:**
- Modify: console/tests/test_environment_store.py
- Modify: console/task_store.py:187-233

- [ ] **Step 1: Add failing store tests**

Add this test while preserving test_store_round_trip_does_not_have_credential_columns:

~~~python
def test_environment_target_credential_ref_can_be_updated_and_cleared(self):
    target_id = self.store.create_environment_target(
        "autodl", "gpu.example", username="root", port=18078
    )
    self.assertEqual(self.store.get_environment_target(target_id)["credential_ref"], "")
    self.store.update_environment_target_credential_ref(target_id, "credential-123")
    self.assertEqual(
        self.store.get_environment_target(target_id)["credential_ref"],
        "credential-123",
    )
    self.store.update_environment_target_credential_ref(target_id, "")
    self.assertEqual(self.store.get_environment_target(target_id)["credential_ref"], "")
~~~

- [ ] **Step 2: Run the store test and confirm missing methods**

~~~powershell
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe' -m unittest console.tests.test_environment_store -v
~~~

Expected: FAIL because get_environment_target and update_environment_target_credential_ref do not exist.

- [ ] **Step 3: Add the two narrow TaskStore methods**

Add next to find_environment_target:

~~~python
def get_environment_target(self, target_id):
    conn = self._connect()
    try:
        row = conn.execute(
            "SELECT * FROM environment_targets WHERE target_id = ?",
            (str(target_id),),
        ).fetchone()
        return self._environment_row(row, {})
    finally:
        conn.close()

def update_environment_target_credential_ref(self, target_id, credential_ref):
    now = _now()
    conn = self._connect()
    try:
        conn.execute(
            "UPDATE environment_targets SET credential_ref = ?, updated_at = ? WHERE target_id = ?",
            (str(credential_ref or ""), now, str(target_id)),
        )
        conn.commit()
    finally:
        conn.close()
~~~

Do not add password, encrypted_password, private_key, or ciphertext columns.

- [ ] **Step 4: Run store tests**

Run the Task 2 command again.

Expected: all environment-store tests PASS.

- [ ] **Step 5: Commit the target-reference methods**

~~~powershell
git add -- console/task_store.py console/tests/test_environment_store.py
git commit -m "feat: link environment targets to saved credentials"
~~~

### Task 3: Integrate Saved Credentials into EnvironmentManager

**Files:**
- Modify: console/tests/test_environment_api.py
- Modify: console/environment_manager.py:1-108,227-236

- [ ] **Step 1: Add a fake credential store and failing manager tests**

Add this test double to console/tests/test_environment_api.py:

~~~python
class FakeCredentialStore:
    supported = True

    def __init__(self):
        self.values = {}

    def save(self, password, credential_ref=None):
        ref = credential_ref or "saved-ref"
        self.values[ref] = password
        return ref

    def load(self, credential_ref):
        return self.values.get(credential_ref)

    def delete(self, credential_ref):
        return self.values.pop(credential_ref, None) is not None
~~~

Construct EnvironmentManager with credential_store=self.credentials and add tests covering all required flows:

~~~python
def test_successful_scan_can_save_and_reuse_password(self):
    captured = []
    self.manager.session_factory = lambda connection, credential=None: (
        captured.append(dict(credential or {})) or self.session
    )
    first = self.manager.scan_target({
        "platform": "autodl",
        "ssh_command": "ssh root@host",
        "password": "secret",
        "remember_password": True,
    })
    self.assertTrue(first["credential_saved"])
    self.assertTrue(first["has_saved_password"])
    self.assertNotIn("secret", json.dumps(first, ensure_ascii=False))
    second = self.manager.scan_target({
        "platform": "autodl",
        "ssh_command": "ssh root@host",
        "password": "",
    })
    self.assertEqual(captured[-1]["password"], "secret")
    self.assertTrue(second["has_saved_password"])

def test_password_is_not_saved_when_authentication_fails(self):
    class FailingSession(FakeSSHSession):
        def observe_fingerprint(self):
            raise EnvironmentError("SSH 认证失败", "E-SSH-AUTH")
    manager = EnvironmentManager(
        self.store,
        session_factory=lambda *args, **kwargs: FailingSession(),
        credential_store=self.credentials,
    )
    with self.assertRaises(EnvironmentError):
        manager.scan_target({
            "platform": "autodl",
            "ssh_command": "ssh root@host",
            "password": "wrong",
            "remember_password": True,
        })
    self.assertEqual(self.credentials.values, {})

def test_saved_password_auth_failure_is_marked_without_exposing_password(self):
    target_id = self.store.create_environment_target(
        "autodl", "host", username="root", credential_ref="saved-ref"
    )
    self.credentials.values["saved-ref"] = "old-secret"
    class FailingSession(FakeSSHSession):
        def observe_fingerprint(self):
            raise EnvironmentError("SSH 认证失败", "E-SSH-AUTH")
    manager = EnvironmentManager(
        self.store,
        session_factory=lambda *args, **kwargs: FailingSession(),
        credential_store=self.credentials,
    )
    with self.assertRaises(EnvironmentError) as ctx:
        manager.scan_target({"platform": "autodl", "ssh_command": "ssh root@host"})
    self.assertTrue(ctx.exception.details["saved_credential_invalid"])
    self.assertEqual(self.store.get_environment_target(target_id)["credential_ref"], "saved-ref")
    self.assertNotIn("old-secret", str(ctx.exception.details))

def test_credential_status_and_clear_are_target_scoped(self):
    scan = self.manager.scan_target({
        "platform": "autodl",
        "ssh_command": "ssh root@host",
        "password": "secret",
        "remember_password": True,
    })
    status = self.manager.get_credential_status("autodl", "ssh root@host")
    self.assertEqual(status["target_id"], scan["target_id"])
    self.assertTrue(status["has_saved_password"])
    cleared = self.manager.clear_saved_password(scan["target_id"])
    self.assertFalse(cleared["has_saved_password"])
    self.assertFalse(self.manager.clear_saved_password(scan["target_id"])["has_saved_password"])
~~~

- [ ] **Step 2: Run manager tests and confirm constructor/behavior failures**

~~~powershell
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe' -m unittest console.tests.test_environment_api -v
~~~

Expected: FAIL because EnvironmentManager does not accept credential_store and has no status/clear behavior.

- [ ] **Step 3: Implement credential resolution and non-secret status helpers**

Import EnvironmentCredentialStore and CredentialStoreError in both package and script import branches. Change the constructor to:

~~~python
def __init__(self, store, session_factory=None, downloader_factory=None,
             verifier=None, credential_store=None):
    self.store = store
    self.credential_store = credential_store or EnvironmentCredentialStore()
~~~

Add:

~~~python
def get_credential_status(self, platform, ssh_command):
    connection = parse_ssh_command(ssh_command)
    target = self.store.find_environment_target(
        platform or "unknown", connection.host, connection.username, connection.port
    )
    ref = str((target or {}).get("credential_ref") or "")
    has_saved = bool(ref and self.credential_store.supported)
    if has_saved:
        try:
            has_saved = self.credential_store.load(ref) is not None
        except CredentialStoreError:
            has_saved = False
    return {
        "credential_storage_supported": self.credential_store.supported,
        "target_id": (target or {}).get("target_id", ""),
        "has_saved_password": has_saved,
    }

def clear_saved_password(self, target_id):
    target = self.store.get_environment_target(target_id)
    if not target:
        raise EnvironmentError("环境目标不存在", "E-VERIFY")
    ref = str(target.get("credential_ref") or "")
    if ref:
        self.credential_store.delete(ref)
        self.store.update_environment_target_credential_ref(target_id, "")
    return {
        "credential_storage_supported": self.credential_store.supported,
        "target_id": target_id,
        "has_saved_password": False,
    }
~~~

- [ ] **Step 4: Update scan_target with the post-auth save rule**

In scan_target, find the existing target before building credential. Track supplied_password separately from a loaded password:

~~~python
supplied_password = str(payload.get("password") or "")
password = supplied_password
used_saved_password = False
existing_ref = str((existing or {}).get("credential_ref") or "")
if not password and existing_ref:
    try:
        password = self.credential_store.load(existing_ref) or ""
        used_saved_password = bool(password)
    except CredentialStoreError:
        password = ""
if password:
    credential["password"] = password
~~~

Wrap authenticated scanning so an E-SSH-AUTH failure caused by a loaded password adds only this safe detail:

~~~python
except EnvironmentError as exc:
    if used_saved_password and exc.code == "E-SSH-AUTH":
        exc.details = dict(exc.details or {})
        exc.details["saved_credential_invalid"] = True
    raise
~~~

Create new targets with credential_ref="". After the scan succeeds and target_id exists, save only when remember_password is true and supplied_password is non-empty:

~~~python
credential_saved = None
if bool(payload.get("remember_password")) and supplied_password:
    try:
        ref = self.credential_store.save(supplied_password, existing_ref or None)
        self.store.update_environment_target_credential_ref(target_id, ref)
        credential_saved = True
    except CredentialStoreError:
        credential_saved = False
target = self.store.get_environment_target(target_id)
has_saved_password = bool(
    self.credential_store.supported and (target or {}).get("credential_ref")
)
~~~

Return credential_storage_supported, has_saved_password, and credential_saved beside target_id, scan_id, and scan. Never include password, ciphertext, protector errors, or credential_ref in the response.

- [ ] **Step 5: Run manager and store tests**

~~~powershell
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe' -m unittest console.tests.test_environment_credentials console.tests.test_environment_store console.tests.test_environment_api -v
~~~

Expected: all tests PASS.

- [ ] **Step 6: Commit manager integration**

~~~powershell
git add -- console/environment_manager.py console/tests/test_environment_api.py
git commit -m "feat: reuse saved SSH passwords for environment scans"
~~~

### Task 4: Add Credential Status and Clear API Routes

**Files:**
- Modify: console/tests/test_environment_api_routes.py
- Modify: console/batch_console.py:4388-4422,4694-4710

- [ ] **Step 1: Add failing route-registration and safety assertions**

Extend the route tuple with:

~~~python
"/api/environments/credentials/status",
"/api/environments/credentials/clear",
~~~

Add a source-level safety test:

~~~python
def test_credential_routes_return_status_only(self):
    source = Path(batch_console.__file__).read_text(encoding="utf-8")
    status_route = source.split(
        'if path.path == "/api/environments/credentials/status":', 1
    )[1].split("if path.path.startswith", 1)[0]
    clear_route = source.split(
        'if path == "/api/environments/credentials/clear":', 1
    )[1].split('if path == "/api/environments/plan":', 1)[0]
    self.assertIn("get_credential_status", status_route)
    self.assertIn("clear_saved_password", clear_route)
    self.assertNotIn('["password"]', status_route + clear_route)
~~~

- [ ] **Step 2: Run route tests and confirm missing routes**

~~~powershell
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe' -m unittest console.tests.test_environment_api_routes -v
~~~

Expected: FAIL because both credential routes are absent.

- [ ] **Step 3: Add the GET status route**

In do_GET, use the already parsed URL object and parse_qs:

~~~python
if path.path == "/api/environments/credentials/status":
    query = urllib.parse.parse_qs(path.query)
    platform = (query.get("platform") or ["unknown"])[0]
    ssh_command = (query.get("ssh_command") or [""])[0]
    try:
        result = get_environment_manager().get_credential_status(platform, ssh_command)
        self._send(200, json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        code = getattr(exc, "code", "E-VERIFY")
        self._send(400, json.dumps({"error_code": code, "error": str(exc)}, ensure_ascii=False))
    return
~~~

- [ ] **Step 4: Add the POST clear route**

Place it after the scan route and before the plan route:

~~~python
if path == "/api/environments/credentials/clear":
    try:
        result = get_environment_manager().clear_saved_password(body.get("target_id"))
        self._send(200, json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        code = getattr(exc, "code", "E-VERIFY")
        self._send(400, json.dumps({"error_code": code, "error": str(exc)}, ensure_ascii=False))
    return
~~~

Do not accept a file path, credential_ref, password, or ciphertext from the browser.

- [ ] **Step 5: Run route and manager tests**

~~~powershell
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe' -m unittest console.tests.test_environment_api_routes console.tests.test_environment_api -v
~~~

Expected: all tests PASS.

- [ ] **Step 6: Commit API routes**

~~~powershell
git add -- console/batch_console.py console/tests/test_environment_api_routes.py
git commit -m "feat: expose saved SSH credential controls"
~~~

### Task 5: Add Remember, Status, and Clear Controls to the UI

**Files:**
- Modify: console/tests/test_environment_ui.py
- Modify: console/index.html:647-666,2362-2485,3901-3936

- [ ] **Step 1: Add failing UI assertions**

Add tests that require all controls, payload fields, routes, and bindings:

~~~python
def test_environment_password_can_be_remembered_and_cleared_safely(self):
    for marker in (
        'id="environmentRememberPassword"',
        'id="environmentCredentialStatus"',
        'id="btnEnvironmentClearPassword"',
        "remember_password:",
        "refreshEnvironmentCredentialStatus",
        "clearEnvironmentSavedPassword",
        "/api/environments/credentials/status",
        "/api/environments/credentials/clear",
    ):
        self.assertIn(marker, self.source)
    self.assertNotIn("localStorage.setItem(environmentPassword", self.source)
    self.assertNotIn("sessionStorage.setItem(environmentPassword", self.source)
~~~

Extend the event-binding test with btnEnvironmentClearPassword and a change/blur binding for environmentSshCommand that refreshes credential status.

- [ ] **Step 2: Run UI tests and confirm missing controls**

~~~powershell
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe' -m unittest console.tests.test_environment_ui -v
~~~

Expected: FAIL because the remember/status/clear UI does not exist.

- [ ] **Step 3: Add the controls beside the existing password field**

Use the existing environment-grid and environment-actions styles:

~~~html
<label class="field">SSH 密码
  <input type="password" id="environmentPassword" autocomplete="new-password" placeholder="可留空使用已保存密码">
</label>
<label class="field" style="justify-content:flex-end">
  <span><input type="checkbox" id="environmentRememberPassword"> 记住 SSH 密码</span>
  <small id="environmentCredentialStatus" class="hint">未保存密码</small>
</label>
~~~

Add a disabled button to the first environment-actions row:

~~~html
<button class="btn" id="btnEnvironmentClearPassword" disabled>清除已保存密码</button>
~~~

- [ ] **Step 4: Add status rendering and refresh functions**

Add these functions near environmentSetSummary:

~~~javascript
function renderEnvironmentCredentialStatus(status) {
  status = status || {};
  const supported = status.credential_storage_supported !== false;
  const saved = Boolean(status.has_saved_password);
  environmentState.targetId = status.target_id || environmentState.targetId || '';
  $('environmentCredentialStatus').textContent = !supported
    ? '当前系统不支持安全保存'
    : (saved ? '已安全保存，密码框可留空' : '未保存密码');
  $('btnEnvironmentClearPassword').disabled = !saved || !environmentState.targetId;
}

async function refreshEnvironmentCredentialStatus() {
  const sshCommand = $('environmentSshCommand').value.trim();
  if (!sshCommand) {
    renderEnvironmentCredentialStatus({has_saved_password:false});
    return;
  }
  const params = new URLSearchParams({
    platform: $('environmentPlatform').value,
    ssh_command: sshCommand,
  });
  const response = await fetch('/api/environments/credentials/status?' + params.toString());
  const data = await response.json();
  if (response.ok) renderEnvironmentCredentialStatus(data);
}
~~~

Failures in refresh are non-fatal: retain “未保存密码” and allow manual password entry.

- [ ] **Step 5: Add remember payload, scan-result status, and clear action**

Add to environmentScanPayload:

~~~javascript
remember_password: Boolean($('environmentRememberPassword').checked),
~~~

After a successful scan, call:

~~~javascript
renderEnvironmentCredentialStatus(d);
if ($('environmentRememberPassword').checked && d.credential_saved === false) {
  environmentSetSummary('environmentScanSummary', '扫描成功，但 SSH 密码未能安全保存。', 'warn');
}
~~~

When an error response contains details.saved_credential_invalid, show “已保存密码失效，请重新输入或清除” and keep the clear button available.

Add:

~~~javascript
async function clearEnvironmentSavedPassword() {
  if (!environmentState.targetId) return;
  const response = await fetch('/api/environments/credentials/clear', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({target_id:environmentState.targetId}),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '清除已保存密码失败');
  $('environmentPassword').value = '';
  $('environmentRememberPassword').checked = false;
  renderEnvironmentCredentialStatus(data);
  environmentSetSummary('environmentScanSummary', '已清除本机保存的 SSH 密码。', 'ok');
}
~~~

- [ ] **Step 6: Bind controls and refresh after loading the saved SSH command**

Add bindings near line 3901:

~~~javascript
$('btnEnvironmentClearPassword').addEventListener('click', () => {
  clearEnvironmentSavedPassword().catch(e => environmentSetSummary('environmentScanSummary', e.message, 'error'));
});
$('environmentSshCommand').addEventListener('change', refreshEnvironmentCredentialStatus);
$('environmentPlatform').addEventListener('change', refreshEnvironmentCredentialStatus);
~~~

Change the startup call to await loadSavedEnvironmentSshCommand() and then refresh status, using a promise chain because the surrounding script is not an async module:

~~~javascript
loadSavedEnvironmentSshCommand().then(refreshEnvironmentCredentialStatus).catch(() => {});
~~~

- [ ] **Step 7: Run UI and security regression tests**

~~~powershell
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe' -m unittest console.tests.test_environment_ui console.tests.test_environment_api_routes console.tests.test_environment_api -v
~~~

Expected: all tests PASS and no password localStorage assertion regresses.

- [ ] **Step 8: Commit the UI**

~~~powershell
git add -- console/index.html console/tests/test_environment_ui.py
git commit -m "feat: add SSH password remember and clear controls"
~~~

### Task 6: Document, Verify, and Smoke-Test the Feature

**Files:**
- Modify: console/CHANGELOG.md

- [ ] **Step 1: Add the mandatory changelog entry**

Insert v0.13.92 at the top of console/CHANGELOG.md with:

- Added Windows DPAPI-encrypted, per-target SSH password memory.
- Added saved-password state and clear action to cloud environment deployment.
- Clarified that plaintext is never stored in SQLite, config.json, browser storage, logs, or API responses.
- Verification commands and the manual Win10 scan/reuse/clear sequence.

- [ ] **Step 2: Run focused tests**

~~~powershell
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe' -m unittest console.tests.test_environment_credentials console.tests.test_environment_store console.tests.test_environment_api console.tests.test_environment_api_routes console.tests.test_environment_ui -v
~~~

Expected: all focused tests PASS.

- [ ] **Step 3: Run the complete regression suite**

~~~powershell
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe' -m unittest discover -s console/tests -p "test_*.py" -v
~~~

Expected: all tests PASS with no failures or errors.

- [ ] **Step 4: Compile and inspect the final diff**

~~~powershell
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe' -m compileall -q console
git diff --check
rg -n "localStorage.*[Pp]assword|sessionStorage.*[Pp]assword|encrypted_password|password TEXT|private_key TEXT" console
~~~

Expected: compileall and git diff --check exit 0. The security grep must find no new password storage code; the existing password input and request payload are acceptable only when they do not write browser or database storage.

- [ ] **Step 5: Restart the console and perform the Win10 smoke test**

Restart using the project command:

~~~powershell
Set-Location console
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe' start_daemons.py
~~~

Then verify in the 8890 UI:

1. Enter the AutoDL SSH command and password, check “记住 SSH 密码,” and scan successfully.
2. Refresh the page; confirm “已安全保存，密码框可留空.”
3. Leave the password blank and scan successfully.
4. Click “清除已保存密码”; confirm the status becomes “未保存密码.”
5. Scan with the password blank and confirm the UI requests credentials instead of silently falling back.
6. Inspect console logs and API responses for the unique test password marker; it must not appear.

- [ ] **Step 6: Commit changelog and final verification state**

~~~powershell
git add -- console/CHANGELOG.md
git commit -m "docs: record secure SSH password memory"
git status --short
~~~

Expected: the feature files are committed; pre-existing unrelated workspace changes remain untouched.
