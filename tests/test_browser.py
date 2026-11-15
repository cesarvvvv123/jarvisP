"""Tes fitur browser (Claude in Chrome) tanpa mic, tanpa Claude, tanpa Chrome:
flag per mode, semua situs boleh, klik/ketik tidak ditanya, saklar "tanya dulu", data pribadi, log.

Pakai:  python tests\\test_browser.py
"""
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import browser_guard as bg  # noqa: E402
import jarvis  # noqa: E402
from test_perbaikan import bare_jarvis  # noqa: E402

C = bg.CHROME_MCP

# semua file yang ditulis tes dialihkan ke folder sementara
TMP = tempfile.mkdtemp()
jarvis.BROWSER_STATE_DIR = os.path.join(TMP, "browser")
jarvis.BROWSER_LOG_PATH = os.path.join(TMP, "jarvis_browser.log")
jarvis.STATE_PATH = os.path.join(TMP, "session_state.json")
jarvis.SETTINGS_PATH = os.path.join(TMP, "settings.json")


def opt(cmd, name):
    i = cmd.index(name) + 1
    out = []
    while i < len(cmd) and not cmd[i].startswith("--"):
        out.append(cmd[i])
        i += 1
    return out


class FakeSp:
    ok = True

    def __init__(self):
        self.said = []

    def say(self, t):
        self.said.append(t)

    def say_answer(self, t):
        self.said.append(t)
        return len(t)


def jv(**settings):
    j = bare_jarvis(tempfile.gettempdir(), **settings)
    j.record = lambda *a, **k: None
    j.spoken = []
    j.speak = j.spoken.append
    j.prewarm_claude = lambda: None
    j.browser_ready_check = lambda: []
    j.browser_log_line = lambda *a: None
    j.turn_shown = False
    return j


def tab(host="example.com", sensitive=False, refs=None):
    return {"1": {"host": host, "url": host + "/", "sensitive": sensitive, "refs": refs or {}}}


def clean_state():
    bg.save_json("requests.json", [], jarvis.BROWSER_STATE_DIR)
    bg.clear_grants(jarvis.BROWSER_STATE_DIR)


# ---------------------------------------------------------------------------
class TestFlag(unittest.TestCase):
    def test_off_direct(self):
        cmd = jv(browser_mode="off", run_mode="direct").claude_cmd(None)
        self.assertIn("--no-chrome", cmd)
        self.assertEqual(opt(cmd, "--permission-mode"), ["bypassPermissions"])
        self.assertNotIn("--settings", cmd)
        self.assertNotIn(jarvis.BROWSER_PROMPT, opt(cmd, "--system-prompt")[0])

    def test_chrome(self):
        cmd = jv(browser_mode="chrome", run_mode="direct").claude_cmd(None)
        self.assertIn("--chrome", cmd)
        self.assertEqual(opt(cmd, "--permission-mode"), ["acceptEdits"])
        system = opt(cmd, "--system-prompt")[0]
        self.assertIn(jarvis.BROWSER_PROMPT, system)
        self.assertIn("Semua situs boleh", system)
        self.assertNotIn(jarvis.BROWSER_CONFIRM_PROMPT, system)           # saklar mati: tidak disuruh bertanya
        hooks = json.loads(opt(cmd, "--settings")[0])["hooks"]
        self.assertEqual(set(hooks), {"PreToolUse", "PostToolUse"})
        self.assertIn(C + "*", opt(cmd, "--allowedTools"))              # item di dalam browser_batch ikut lolos

    def test_chrome_tanya_dulu(self):
        system = opt(jv(browser_mode="chrome", browser_confirm=True).claude_cmd(None), "--system-prompt")[0]
        self.assertIn(jarvis.BROWSER_CONFIRM_PROMPT, system)
        self.assertIn("PERLU_IZIN", system)
        self.assertIn(jarvis.BROWSER_CONFIRM_PROMPT, jarvis.browser_reminder(True))
        self.assertNotIn(jarvis.BROWSER_CONFIRM_PROMPT, jarvis.browser_reminder(False))

    def test_kunci_sesi_dan_env(self):
        seen = []

        class FakeSession:
            def __init__(self, cmd, cwd, env, key):
                seen.append(env)
                self.key = key

            def alive(self):
                return True

            def kill(self, tree=False):
                pass
        old = jarvis.ClaudeSession
        try:
            jarvis.ClaudeSession = FakeSession
            j = jv(browser_mode="chrome")
            j.get_session(None)
            j.get_session(None)
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0]["JARVIS_BROWSER_CONFIRM"], "0")
            self.assertNotIn("JARVIS_BROWSER_SITES", seen[0])
            j.settings["browser_confirm"] = True
            j.get_session(None)
            self.assertEqual(len(seen), 2)                     # saklar berubah: sesi baru
            self.assertEqual(seen[1]["JARVIS_BROWSER_CONFIRM"], "1")
        finally:
            jarvis.ClaudeSession = old


# ---------------------------------------------------------------------------
class TestHook(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def d(self, name, inp, confirm=False, tabs=None):
        dec, kind, _, _ = bg.decide(C + name, inp, confirm, tabs if tabs is not None else tab(), self.dir)
        return dec, kind

    def test_situs_apa_pun_terbuka(self):
        for url in ("https://example.com", "youtube.com", "https://evil.io/x", "about:blank", "back"):
            for confirm in (False, True):
                self.assertEqual(self.d("navigate", {"url": url, "tabId": 1}, confirm), ("allow", ""), url)
        for host in ("evil.io", "iana.org", ""):
            self.assertEqual(self.d("get_page_text", {"tabId": 1}, tabs=tab(host)), ("allow", ""), host)

    def test_klik_ketik_tidak_ditanya(self):
        for confirm in (False, True):
            for tabs in (tab("evil.io"), {}):                           # situs mana pun, tab belum dikenal
                for name, inp in (
                        ("computer", {"action": "left_click", "tabId": 1, "action_summary": "Opens the menu"}),
                        ("computer", {"action": "type", "tabId": 1, "text": "resep rendang"}),
                        ("form_input", {"ref": "ref_2", "tabId": 1, "value": "2", "action_summary": "Sets qty"}),
                        ("computer", {"action": "key", "tabId": 1, "text": "Return"}),
                        ("computer", {"action": "screenshot", "tabId": 1})):
                    self.assertEqual(self.d(name, inp, confirm, tabs), ("allow", ""), (name, inp, confirm))

    def test_belanja_selalu_ditolak(self):
        for confirm in (False, True):
            for summary in ("Clicks Buy now", "Klik tombol Bayar", "Clicks Add to cart", "Klik Checkout",
                            "Klik Beli Sekarang", "Clicks Place order", "Klik Transfer"):
                self.assertEqual(self.d("computer", {"action": "left_click", "tabId": 1, "action_summary": summary},
                                        confirm), ("deny", "belanja"), (summary, confirm))
        bg.grant([{"kind": "izin", "tool": "computer", "action": "left_click", "host": "example.com"}], self.dir)
        self.assertEqual(self.d("computer", {"action": "left_click", "tabId": 1, "action_summary": "Clicks Buy now"},
                                True), ("deny", "belanja"))                  # izin sekali pakai tidak berlaku

    def test_saklar_mati_semua_jalan(self):
        for summary in ("Sends the reply", "Deletes the file", "Publishes the post", "Clicks Subscribe"):
            self.assertEqual(self.d("computer", {"action": "left_click", "tabId": 1, "action_summary": summary}),
                             ("allow", ""), summary)
        self.assertEqual(self.d("computer", {"action": "key", "tabId": 1, "text": "Enter"},
                                tabs=tab(sensitive=True)), ("allow", ""))
        self.assertEqual(self.d("javascript_tool", {"tabId": 1}), ("allow", ""))

    def test_saklar_nyala_ditanya(self):
        for summary in ("Sends the reply", "Deletes the file", "Publishes the post", "Kirim pesan"):
            self.assertEqual(self.d("computer", {"action": "left_click", "tabId": 1, "action_summary": summary}, True),
                             ("deny", "izin"), summary)
        self.assertEqual(self.d("computer", {"action": "key", "tabId": 1, "text": "Enter"}, True,
                                tab(sensitive=True)), ("deny", "izin"))
        self.assertEqual(self.d("javascript_tool", {"tabId": 1}, True), ("deny", "izin"))

    def test_izin_sekali_pakai(self):
        inp = {"action": "left_click", "tabId": 1, "action_summary": "Sends the reply"}
        bg.grant([{"kind": "izin", "tool": "computer", "action": "left_click", "host": "example.com"}], self.dir)
        self.assertEqual(self.d("computer", inp, True), ("allow", ""))
        self.assertEqual(self.d("computer", inp, True), ("deny", "izin"))

    def test_data_pribadi_selalu_ditolak(self):
        refs = {"ref_3": 'textbox "Password" [ref_3]', "ref_5": 'textbox "Search" [ref_5]'}
        for confirm in (False, True):
            t = tab(refs=refs)
            self.assertEqual(self.d("form_input", {"ref": "ref_3", "tabId": 1, "value": "abc"}, confirm, t),
                             ("deny", "pribadi"))
            self.assertEqual(self.d("form_input", {"ref": "ref_5", "tabId": 1, "value": "4111 1111 1111 1111"},
                                    confirm, t), ("deny", "pribadi"))
            self.assertEqual(self.d("computer", {"action": "type", "tabId": 1, "text": "budi@contoh.id"}, confirm, t),
                             ("deny", "pribadi"))
            self.assertEqual(self.d("computer", {"action": "left_click", "tabId": 1, "ref": "ref_3"}, confirm, t)[0],
                             "allow")
            self.assertEqual(self.d("computer", {"action": "type", "tabId": 1, "text": "rahasia"}, confirm, t),
                             ("deny", "pribadi"))

    def test_batch(self):
        acts = [{"name": "navigate", "input": {"url": "evil.io", "tabId": 1}},
                {"name": "computer", "input": {"action": "left_click", "tabId": 1, "action_summary": "Sends it"}}]
        self.assertEqual(self.d("browser_batch", {"actions": acts}), ("allow", ""))
        self.assertEqual(self.d("browser_batch", {"actions": acts}, True), ("deny", "izin"))

    def test_kode_situs_sudah_dihapus(self):
        for name in ("site_allowed", "blocked_sites", "mentioned_sites", "SITE_DENIED", "EMPTY_DENIED"):
            self.assertFalse(hasattr(bg, name), name)
        self.assertNotIn("browser_allowed_sites", jarvis.DEFAULTS)
        self.assertFalse(jarvis.DEFAULTS["browser_confirm"])


class TestProgramHook(unittest.TestCase):
    def run_hook(self, confirm, tool, inp):
        d = tempfile.mkdtemp()
        env = dict(os.environ, JARVIS_BROWSER_CONFIRM=confirm, JARVIS_BROWSER_STATE=d)
        env.pop("JARVIS_BROWSER_SITES", None)
        payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": C + tool, "tool_input": inp})
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), "browser_guard.py")],
                           input=payload, capture_output=True, text=True, env=env, timeout=20)
        return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"]

    def test_saklar_lewat_env(self):
        send = {"action": "left_click", "tabId": 5, "action_summary": "Sends the message"}
        self.assertEqual(self.run_hook("0", "computer", send), "allow")
        self.assertEqual(self.run_hook("1", "computer", send), "deny")
        self.assertEqual(self.run_hook("0", "navigate", {"url": "https://evil.io"}), "allow")


# ---------------------------------------------------------------------------
class TestJarvis(unittest.TestCase):
    def setUp(self):
        clean_state()

    def test_situs_apa_pun_ke_claude(self):
        j = jv(browser_mode="chrome")
        j.hold_lock, j.hold_timer, j.hold_notes, j.hold_dur = threading.Lock(), None, [""], 1.0
        j.hold_text = ["buka youtube.com sekarang"]
        sent = []
        j.run_turn = lambda t, **k: sent.append(t)
        j.dispatch()
        self.assertEqual(sent, ["buka youtube.com sekarang"])
        self.assertEqual(j.spoken, [])

    def test_suara_aktifkan_tanpa_syarat(self):
        j = jv(browser_mode="off")
        j.handle_browser_command("on")
        self.assertEqual(j.settings["browser_mode"], "chrome")
        self.assertTrue(j.spoken[-1].startswith("Browser aktif"))
        self.assertEqual(j.toggle_browser(), "off")
        self.assertEqual(j.toggle_browser(), "chrome")

    def test_pengaturan_saklar(self):
        j = jv()
        j.show_folder = lambda: None
        self.assertIsNone(j.apply_settings({"browser_mode": "chrome", "browser_confirm": True}))
        self.assertTrue(j.browser_confirm())
        self.assertIsNone(j.apply_settings({"browser_confirm": False}))
        self.assertFalse(j.browser_confirm())

    def test_izin_ditanya_lalu_ya(self):
        j = jv(browser_mode="chrome", browser_confirm=True)
        bg.add_request({"kind": "izin", "tool": "computer", "action": "left_click", "host": "example.com",
                        "label": "klik: Sends the reply"}, jarvis.BROWSER_STATE_DIR)
        j.ask_claude = lambda *a: (None, [], [])
        sp = FakeSp()
        j._run_turn("balas email", None, sp)
        self.assertEqual(sp.said, ["Claude mau klik: Sends the reply di browser. Izinkan? Katakan ya atau tidak."])
        j.hold_lock, j.hold_timer, j.hold_notes, j.hold_dur = threading.Lock(), None, [""], 1.0
        j.hold_text = ["ya"]
        calls = []
        j.run_turn = lambda t, allow=None, **k: calls.append(allow)
        j.dispatch()
        self.assertEqual(calls, [None])
        self.assertEqual(len(bg.load_json("grants.json", [], jarvis.BROWSER_STATE_DIR)), 1)

    def test_pribadi_diumumkan(self):
        j = jv(browser_mode="chrome")
        bg.add_request({"kind": "pribadi", "tool": "form_input", "action": "", "host": "x.com", "label": "x"},
                       jarvis.BROWSER_STATE_DIR)
        j.ask_claude = lambda *a: (None, [], [])
        sp = FakeSp()
        j._run_turn("isi form", None, sp)
        self.assertEqual(sp.said, [bg.PRIVATE_DENIED])


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
    def test_stream_log_dan_layar(self):
        if os.path.exists(jarvis.BROWSER_LOG_PATH):
            os.remove(jarvis.BROWSER_LOG_PATH)
        evs = [{"type": "assistant", "message": {"content": [
                   {"type": "tool_use", "id": "t1", "name": C + "navigate", "input": {"url": "https://evil.io/p?t=RHS"}},
                   {"type": "tool_use", "id": "t2", "name": C + "form_input", "input": {"ref": "r1", "value": "rhs123"}}]}},
               {"type": "result", "result": "UCAPAN: Beres.\nLAYAR: -", "modelUsage": {}}]
        j = bare_jarvis(tempfile.gettempdir(), browser_mode="chrome")
        j.record = lambda *a, **k: None
        s = FakeStream(evs)
        j.get_session = lambda allow: s
        _, _, tools = j.ask_claude("buka evil.io", None, FakeSp())
        self.assertIn(jarvis.browser_reminder(False), s.sent)
        with open(jarvis.BROWSER_LOG_PATH, encoding="utf-8") as f:
            log = f.read()
        self.assertIn("evil.io/p", log)
        self.assertNotIn("RHS", log)
        self.assertNotIn("rhs123", log + json.dumps(tools))
        self.assertIn("Browser: membuka evil.io", [t for _, t in j.ui.logs])

    def test_timeout_600_dan_esc(self):
        j = jv(browser_mode="chrome")
        s = FakeStream([])
        j.sess = s
        j.get_session = lambda allow: s
        old_c, old_b = jarvis.CLAUDE_TIMEOUT, jarvis.BROWSER_TIMEOUT
        try:
            self.assertEqual(old_b, 600)
            jarvis.CLAUDE_TIMEOUT, jarvis.BROWSER_TIMEOUT = 10_000, 0
            self.assertEqual(j.ask_claude("halo"), (None, [], []))
        finally:
            jarvis.CLAUDE_TIMEOUT, jarvis.BROWSER_TIMEOUT = old_c, old_b
        self.assertEqual(s.killed, [True])
        j.hold_lock, j.hold_timer, j.hold_text, j.hold_notes, j.hold_dur = threading.Lock(), None, [], [], 0.0
        j.listener_on = False
        s2 = FakeStream([])
        j.sess, j.busy = s2, True
        j.cancel()
        self.assertEqual(s2.killed, [True])
        self.assertTrue(any("tab browser" in t for _, t in j.ui.logs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
