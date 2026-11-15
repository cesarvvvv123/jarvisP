"""Tes kontrol komputer (Windows-MCP) tanpa mic, tanpa Claude, tanpa server MCP:
flag per mode, penggabungan dengan browser, perintah suara, label panel, log tanpa teks ketikan.

Pakai:  python tests\\test_desktop.py
"""
import json
import os
import queue
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import browser_guard as bg  # noqa: E402
import desktop  # noqa: E402
import jarvis  # noqa: E402
from test_perbaikan import bare_jarvis  # noqa: E402

TMP = tempfile.mkdtemp()
jarvis.DESKTOP_LOG_PATH = os.path.join(TMP, "jarvis_desktop.log")
jarvis.BROWSER_LOG_PATH = os.path.join(TMP, "jarvis_browser.log")
jarvis.BROWSER_STATE_DIR = os.path.join(TMP, "browser")
jarvis.SETTINGS_PATH = os.path.join(TMP, "settings.json")
jarvis.STATE_PATH = os.path.join(TMP, "session_state.json")

SNAPSHOT = """
    Cursor Position: (120, 40)
    Focused Window:
    Name                         Depth  Status       Width    Height    Handle
-------------------------  -------  ---------  -------  --------  --------
Untitled - Notepad               0  Normal         800       600    123456
    UI Tree:
    Window "Untitled - Notepad"
    ├── (40,20) MenuItem "File"  [focused: False]
    ├── (90,20) MenuItem "Edit"  [focused: False]
    ├── (400,300) Document "Text editor"  [focused: True]
    └── (700,560) Button "Simpan"  [focused: False]
"""


def opt(cmd, name):
    i = cmd.index(name) + 1
    out = []
    while i < len(cmd) and not cmd[i].startswith("--"):
        out.append(cmd[i])
        i += 1
    return out


def jv(**settings):
    j = bare_jarvis(tempfile.gettempdir(), **settings)
    j.record = lambda *a, **k: None
    j.spoken = []
    j.speak = j.spoken.append
    j.prewarm_claude = lambda: None
    j.desktop_ready_check = lambda: []
    j.browser_ready_check = lambda: []
    j.browser_log_line = lambda *a: None
    j.turn_shown = False
    return j


class TestFlag(unittest.TestCase):
    def test_off_tidak_berubah(self):
        cmd = jv(desktop_control="off").claude_cmd(None)
        self.assertNotIn("--mcp-config", cmd)
        self.assertNotIn(desktop.PROMPT, opt(cmd, "--system-prompt")[0])
        self.assertFalse(any(c.startswith(desktop.PREFIX) for c in cmd))
        self.assertNotIn("--allowedTools", cmd)                        # direct + browser mati: sama seperti dulu
        self.assertEqual(opt(cmd, "--permission-mode"), ["bypassPermissions"])

    def test_on(self):
        cmd = jv(desktop_control="on").claude_cmd(None)
        self.assertEqual(opt(cmd, "--mcp-config"), [jarvis.MCP_WINDOWS_PATH])   # argumen variadic tidak bocor
        self.assertIn("--strict-mcp-config", cmd)
        self.assertIn(desktop.PROMPT, opt(cmd, "--system-prompt")[0])
        self.assertEqual(opt(cmd, "--system-prompt-snapshot"), ["off"])
        allowed = opt(cmd, "--allowedTools")
        self.assertEqual(sorted(allowed), sorted(desktop.TOOLS))
        for t in ("Screenshot", "Snapshot", "Click", "Type", "Scroll", "Shortcut", "App", "Wait"):
            self.assertIn(desktop.PREFIX + t, allowed)
        for t in ("PowerShell", "Registry"):
            self.assertNotIn(desktop.PREFIX + t, allowed)
        self.assertIn("--no-chrome", cmd)

    def test_digabung_dengan_browser(self):
        cmd = jv(desktop_control="on", browser_mode="chrome").claude_cmd(None)
        self.assertIn("--chrome", cmd)
        self.assertEqual(opt(cmd, "--mcp-config"), [jarvis.MCP_WINDOWS_PATH])
        self.assertEqual(cmd.count("--system-prompt-snapshot"), 1)
        self.assertEqual(cmd.count("--allowedTools"), 1)
        allowed = opt(cmd, "--allowedTools")
        self.assertIn(bg.CHROME_MCP + "*", allowed)
        for t in desktop.TOOLS:
            self.assertIn(t, allowed)
        system = opt(cmd, "--system-prompt")[0]
        self.assertIn(desktop.PROMPT, system)
        self.assertIn(jarvis.BROWSER_PROMPT, system)
        hooks = json.loads(opt(cmd, "--settings")[0])["hooks"]             # hook browser tetap terpasang
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "mcp__claude-in-chrome__.*")

    def test_kunci_sesi(self):
        seen = []

        class FakeSession:
            def __init__(self, cmd, cwd, env, key):
                seen.append(cmd)
                self.key = key

            def alive(self):
                return True

            def kill(self, tree=False):
                pass
        old = jarvis.ClaudeSession
        try:
            jarvis.ClaudeSession = FakeSession
            j = jv(desktop_control="off")
            j.get_session(None)
            j.get_session(None)
            self.assertEqual(len(seen), 1)
            j.settings["desktop_control"] = "on"
            j.get_session(None)
            self.assertEqual(len(seen), 2)
            self.assertIn("--mcp-config", seen[1])
        finally:
            jarvis.ClaudeSession = old

    def test_file_konfigurasi(self):
        with open(jarvis.MCP_WINDOWS_PATH, encoding="utf-8") as f:
            cfg = json.load(f)["mcpServers"][desktop.SERVER]
        self.assertEqual(cfg["command"], "uvx")
        self.assertIn("windows-mcp==0.8.9", cfg["args"])
        self.assertEqual(cfg["args"][cfg["args"].index("--exclude-tools") + 1], "PowerShell,Registry")
        self.assertEqual(cfg["env"]["ANONYMIZED_TELEMETRY"], "false")


class TestSuara(unittest.TestCase):
    def test_kenali(self):
        cases = {"aktifkan kontrol komputer": "on", "Jarvis, aktifkan kontrol komputer": "on", "nyalakan tangan": "on",
                 "matikan kontrol komputer": "off", "matikan tangan": "off", "kontrol komputer aktif nggak?": "ask",
                 "status kontrol komputer": "ask"}
        for t, want in cases.items():
            self.assertEqual(desktop.parse_command(t), want, t)
        for t in ("buat gambar tangan", "nyalakan tangan robot di game", "aktifkan browser", "buka komputer",
                  "kontrol komputer"):
            self.assertIsNone(desktop.parse_command(t), t)

    def test_tangani_dan_dispatch(self):
        j = jv(desktop_control="off")
        j.desktop_log_line = lambda *a: None
        j.hold_lock, j.hold_timer, j.hold_notes, j.hold_dur = threading.Lock(), None, [""], 1.0
        j.run_turn = lambda *a, **k: self.fail("tidak boleh ke Claude")
        for text, mode, reply in (("aktifkan kontrol komputer", "on", "Kontrol komputer aktif."),
                                  ("kontrol komputer aktif nggak?", "on", "Kontrol komputer sedang aktif."),
                                  ("matikan kontrol komputer", "off", "Kontrol komputer dimatikan."),
                                  ("kontrol komputer aktif nggak?", "off", "Kontrol komputer sedang mati.")):
            j.hold_text = [text]
            j.dispatch()
            self.assertEqual((j.settings["desktop_control"], j.spoken[-1]), (mode, reply), text)
        self.assertEqual(j.toggle_desktop(), "on")

    def test_pengaturan(self):
        j = jv()
        j.show_folder = lambda: None
        j.desktop_log_line = lambda *a: None
        self.assertIsNone(j.apply_settings({"desktop_control": "on"}))
        self.assertTrue(j.desktop_on())
        self.assertIsNotNone(j.apply_settings({"desktop_control": "ya"}))


class TestLabel(unittest.TestCase):
    def test_snapshot(self):
        app, elems = desktop.parse_snapshot(SNAPSHOT)
        self.assertEqual(app, "Notepad")
        self.assertEqual(elems[(700, 560)], ("Button", "Simpan"))
        serial = json.dumps([SNAPSHOT])                                 # hasil Windows-MCP: list ter-serialisasi
        self.assertEqual(desktop.parse_snapshot(desktop.response_text([{"type": "text", "text": serial}]))[0],
                         "Notepad")
        shot = "    Focused Window:\nNot listed: Screenshot skips window enumeration. Call Snapshot for windows.\n"
        self.assertEqual(desktop.parse_snapshot(shot)[0], "")          # hasil Screenshot: bukan nama aplikasi

    def test_label(self):
        _, elems = desktop.parse_snapshot(SNAPSHOT)
        P = desktop.PREFIX
        self.assertEqual(desktop.label(P + "Click", {"loc": [702, 558]}, "Notepad", elems), "Klik: Simpan")
        self.assertEqual(desktop.label(P + "Click", {"loc": [5, 5]}, "Notepad", elems), "Klik: titik (5, 5)")
        self.assertEqual(desktop.label(P + "Type", {"text": "RAHASIA", "loc": [400, 300]}, "Notepad", elems),
                         "Ketik di: Notepad (Text editor)")
        self.assertEqual(desktop.label(P + "App", {"mode": "launch", "name": "notepad"}, "", {}), "Buka: notepad")
        self.assertEqual(desktop.label(P + "Shortcut", {"shortcut": "ctrl+s"}, "", {}), "Pintasan: ctrl+s")
        self.assertEqual(desktop.label(P + "Wait", {"duration": 1}, "", {}), "")


class FakeStream:
    def __init__(self, events):
        self.events = queue.Queue()
        for e in events:
            self.events.put(e)
        self.cwd = tempfile.gettempdir()
        self.init, self.init_checked = None, False
        self.killed = []

    def send(self, text, images=None):
        self.sent = text

    def kill(self, tree=False):
        self.killed.append(tree)


class TestAlur(unittest.TestCase):
    def test_stream_log_tanpa_teks(self):
        if os.path.exists(jarvis.DESKTOP_LOG_PATH):
            os.remove(jarvis.DESKTOP_LOG_PATH)
        P = desktop.PREFIX
        evs = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "a", "name": P + "App", "input": {"mode": "launch", "name": "notepad"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "a", "content": "ok"}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "s", "name": P + "Snapshot", "input": {}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "s",
                                                      "content": [{"type": "text", "text": SNAPSHOT}]}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t", "name": P + "Type", "input": {"text": "KATA-RAHASIA", "loc": [400, 300]}},
                {"type": "tool_use", "id": "c", "name": P + "Click", "input": {"loc": [700, 560]}}]}},
            {"type": "result", "result": "UCAPAN: Beres.\nLAYAR: -", "modelUsage": {}},
        ]
        j = bare_jarvis(tempfile.gettempdir(), desktop_control="on")
        j.record = lambda *a, **k: None
        s = FakeStream(evs)
        s.init = {"mcp_servers": [{"name": "windows-mcp", "status": "connected"}], "tools": list(desktop.TOOLS)}
        j.get_session = lambda allow: s
        _, _, tools = j.ask_claude("buka notepad dan ketik", None, None)
        texts = [t for _, t in j.ui.logs]
        for line in ("Buka: notepad", "Melihat layar…", "Ketik di: Notepad (Text editor)", "Klik: Simpan"):
            self.assertIn(line, texts)
        with open(jarvis.DESKTOP_LOG_PATH, encoding="utf-8") as f:
            log = f.read()
        self.assertIn("App | notepad", log)
        self.assertIn("Type | Notepad", log)
        self.assertIn("selesai", log)
        self.assertNotIn("KATA-RAHASIA", log + json.dumps(tools) + json.dumps(texts))
        self.assertFalse(any("Nama tool Windows-MCP berbeda" in t for t in texts))

    def test_server_putus_diberi_tahu(self):
        j = bare_jarvis(tempfile.gettempdir(), desktop_control="on")
        j.record = lambda *a, **k: None
        s = FakeStream([{"type": "result", "result": "UCAPAN: x\nLAYAR: -", "modelUsage": {}}])
        s.init = {"mcp_servers": [{"name": "windows-mcp", "status": "failed"}], "tools": []}
        j.get_session = lambda allow: s
        j.ask_claude("halo")
        self.assertTrue(any("Server Windows-MCP failed" in t for _, t in j.ui.logs))

    def test_timeout_600_dan_esc(self):
        j = jv(desktop_control="on")
        s = FakeStream([])
        j.sess = s
        j.get_session = lambda allow: s
        old_c, old_d = jarvis.CLAUDE_TIMEOUT, jarvis.DESKTOP_TIMEOUT
        try:
            self.assertEqual(old_d, 600)
            jarvis.CLAUDE_TIMEOUT, jarvis.DESKTOP_TIMEOUT = 10_000, 0
            self.assertEqual(j.ask_claude("halo"), (None, [], []))
        finally:
            jarvis.CLAUDE_TIMEOUT, jarvis.DESKTOP_TIMEOUT = old_c, old_d
        self.assertEqual(s.killed, [True])
        j.hold_lock, j.hold_timer, j.hold_text, j.hold_notes, j.hold_dur = threading.Lock(), None, [], [], 0.0
        j.listener_on = False
        s2 = FakeStream([])
        j.sess, j.busy = s2, True
        j.cancel()
        self.assertEqual(s2.killed, [True])


if __name__ == "__main__":
    unittest.main(verbosity=2)
