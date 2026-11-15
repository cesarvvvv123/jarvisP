"""Tes perbaikan 2026-11-12 (tanpa mic, tanpa ElevenLabs/Groq/Claude):
1. env ke claude.exe tanpa ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL / CLAUDE_CODE_OAUTH_TOKEN
2. SpeechSession tetap bersuara (Edge TTS) kalau kunci ElevenLabs tidak ada
3. kill(tree=True) ikut menghentikan proses anak (taskkill /T /F)
4. session_id disimpan per folder, --resume saat dibuka lagi, perintah "percakapan baru"

Pakai:  python tests\\test_perbaikan.py
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import uuid

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jarvis  # noqa: E402


class FakeUI:
    def __init__(self):
        self.logs = []

    def log(self, text, tag="sys"):
        self.logs.append((tag, text))

    def __getattr__(self, name):          # status, folder, level, model, ...: diabaikan
        return lambda *a, **k: None


def bare_jarvis(work_dir, **settings):
    """Objek Jarvis tanpa __init__ (tidak memuat Whisper, tidak membuka mic)."""
    j = jarvis.Jarvis.__new__(jarvis.Jarvis)
    j.ui = FakeUI()
    j.settings = dict(jarvis.DEFAULTS, work_dir=work_dir, projects={}, **settings)
    j.claude = "claude.exe"
    j.api_key = None
    j.sess, j.sess_lock = None, threading.Lock()
    j.session_id, j.session_started = str(uuid.uuid4()), False
    j.tm, j.busy, j.cur_sp, j.pending = {}, False, None, []
    return j


def pid_alive(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


class TestEnv(unittest.TestCase):
    def test_kredensial_dibuang_dan_diperingatkan(self):
        captured = {}

        class FakeSession:
            def __init__(self, cmd, cwd, env, key):
                captured.update(env=env, cwd=cwd)
                self.key = key

            def alive(self):
                return True

        old_env = {k: os.environ.get(k) for k in jarvis.CLAUDE_ENV_BLOCK}
        old_cls = jarvis.ClaudeSession
        try:
            for k in jarvis.CLAUDE_ENV_BLOCK:
                os.environ[k] = "dummy-tes"
            jarvis.ClaudeSession = FakeSession
            j = bare_jarvis(tempfile.gettempdir())
            j.get_session(None)
        finally:
            jarvis.ClaudeSession = old_cls
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        for k in jarvis.CLAUDE_ENV_BLOCK:
            self.assertNotIn(k, captured["env"])
            self.assertTrue(any(k in t and tag == "err" for tag, t in j.ui.logs), f"tidak ada peringatan {k}")
        self.assertEqual(captured["env"].get("MAX_THINKING_TOKENS"), "0")
        self.assertFalse(any("dummy-tes" in t for _, t in j.ui.logs), "nilai rahasia tidak boleh masuk log")

    def test_tanpa_kredensial_tanpa_peringatan(self):
        class FakeSession:
            def __init__(self, cmd, cwd, env, key):
                self.key = key

        old_env = {k: os.environ.pop(k, None) for k in jarvis.CLAUDE_ENV_BLOCK}
        old_cls = jarvis.ClaudeSession
        try:
            jarvis.ClaudeSession = FakeSession
            j = bare_jarvis(tempfile.gettempdir())
            j.get_session(None)
        finally:
            jarvis.ClaudeSession = old_cls
            for k, v in old_env.items():
                if v is not None:
                    os.environ[k] = v
        self.assertFalse(any("[auth]" in t for _, t in j.ui.logs))


class TestSpeech(unittest.TestCase):
    def test_ok_tanpa_kunci_dengan_cadangan(self):
        j = bare_jarvis(tempfile.gettempdir(), voice_id="", fallback_voice=True)
        j.voice_id = lambda: None
        self.assertTrue(jarvis.SpeechSession(j).ok)

    def test_tidak_ok_tanpa_kunci_tanpa_cadangan(self):
        j = bare_jarvis(tempfile.gettempdir(), voice_id="", fallback_voice=False)
        j.voice_id = lambda: None
        self.assertFalse(jarvis.SpeechSession(j).ok)

    def test_fetch_tts_langsung_edge_tanpa_kunci(self):
        j = bare_jarvis(tempfile.gettempdir(), fallback_voice=True)
        j.voice_id = lambda: None
        j.credit = None

        def no_eleven(_):
            raise AssertionError("ElevenLabs tidak boleh dipanggil tanpa kunci")
        j.fetch_elevenlabs = no_eleven
        j.fetch_edge_tts = lambda s: ("edge", s)
        self.assertEqual(j.fetch_tts("halo"), ("edge", "halo"))

    def test_fetch_tts_elevenlabs_kalau_ada_kunci(self):
        j = bare_jarvis(tempfile.gettempdir(), fallback_voice=True)
        j.api_key = "x"
        j.voice_id = lambda: "v"
        j.credit = None
        j.fetch_elevenlabs = lambda s: "pcm"
        self.assertEqual(j.fetch_tts("halo"), ("pcm", jarvis.TTS_RATE))


@unittest.skipUnless(os.name == "nt", "taskkill hanya di Windows")
class TestKillTree(unittest.TestCase):
    CHILD = ("import json, subprocess, sys, time; "
             "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
             "print(json.dumps({'child': p.pid}), flush=True); time.sleep(60)")

    def spawn(self):
        s = jarvis.ClaudeSession([sys.executable, "-c", self.CHILD], tempfile.gettempdir(), dict(os.environ), "k")
        ev = s.events.get(timeout=20)
        self.assertIsNotNone(ev)
        return s, ev["child"]

    def test_tree_true_menghentikan_anak(self):
        s, child = self.spawn()
        self.assertTrue(pid_alive(child))
        s.kill(tree=True)
        s.proc.wait(timeout=10)
        time.sleep(1.0)
        self.assertFalse(pid_alive(s.proc.pid), "induk masih hidup")
        self.assertFalse(pid_alive(child), "proses anak masih hidup")
        self.assertIsNone(s.events.get(timeout=5))           # pembaca stdout berhenti -> None

    def test_tree_false_perilaku_lama(self):
        s, child = self.spawn()
        try:
            s.kill()
            s.proc.wait(timeout=10)
            time.sleep(1.0)
            self.assertFalse(pid_alive(s.proc.pid))
            self.assertTrue(pid_alive(child), "tanpa tree, anak memang tertinggal (alasan perbaikan)")
        finally:
            subprocess.run(["taskkill", "/F", "/PID", str(child)], capture_output=True)

    def test_cancel_pakai_tree(self):
        calls = []

        class S:
            def kill(self, tree=False):
                calls.append(tree)
        j = bare_jarvis(tempfile.gettempdir())
        j.hold_lock, j.hold_timer, j.hold_text, j.hold_notes, j.hold_dur = threading.Lock(), None, [], [], 0.0
        j.listener_on = False
        j.sess, j.busy = S(), True
        j.cancel()
        self.assertEqual(calls, [True])

    def test_timeout_pakai_tree(self):
        import queue
        calls = []

        class S:
            events = queue.Queue()             # tidak pernah ada event -> timeout
            cwd = tempfile.gettempdir()

            def send(self, text):
                pass

            def kill(self, tree=False):
                calls.append(tree)
        j = bare_jarvis(tempfile.gettempdir())
        j.record = lambda *a, **k: None
        j.sess = S()
        j.get_session = lambda allow: j.sess
        old = jarvis.CLAUDE_TIMEOUT
        try:
            jarvis.CLAUDE_TIMEOUT = 0
            self.assertEqual(j.ask_claude("halo"), (None, [], []))
        finally:
            jarvis.CLAUDE_TIMEOUT = old
        self.assertEqual(calls, [True])


class TestSesi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_state, self.old_exists = jarvis.STATE_PATH, jarvis.transcript_exists
        jarvis.STATE_PATH = os.path.join(self.tmp, "session_state.json")
        self.work = os.path.join(self.tmp, "proyek")
        os.makedirs(self.work)

    def tearDown(self):
        jarvis.STATE_PATH, jarvis.transcript_exists = self.old_state, self.old_exists

    def test_kenali_perintah(self):
        for t in ("percakapan baru", "Percakapan baru.", "mulai percakapan baru", "tolong mulai obrolan baru!",
                  "obrolan baru"):
            self.assertTrue(jarvis.is_new_conversation(t), t)
        for t in ("buat percakapan baru di file chat.txt", "percakapan", "baru saja", "pindah ke lms"):
            self.assertFalse(jarvis.is_new_conversation(t), t)

    def test_kenali_salah_tangkap(self):
        # salah tangkap Whisper dari log 14-11 dan variasi lain
        for t in ("Berserakapan baru.", "Oke, coba mulai sesi baru.", "Jarvis, percakapan baru.", "sesi baru",
                  "reset sesi", "reset percakapan", "Percakapan baru, Jarpis."):
            self.assertTrue(jarvis.is_new_conversation(t), t)
        # pertanyaan / perintah biasa: jangan sampai mereset sesi
        for t in ("Kapan baru Jarpis?", "kapan baru?", "percobaan baru", "perusahaan baru", "sesi baru kemarin gimana",
                  "buka file baru", "bikin proyek baru"):
            self.assertFalse(jarvis.is_new_conversation(t), t)

    def _transcript(self, tokens, age_h=0):
        path = os.path.join(self.tmp, "sesi.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "halo"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"usage": {
                "input_tokens": 2, "cache_creation_input_tokens": 100, "cache_read_input_tokens": tokens}}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"model": "<synthetic>", "usage": {
                "input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}}) + "\n")
        t = time.time() - age_h * 3600
        os.utime(path, (t, t))
        return path

    def test_ukuran_konteks_dari_transkrip(self):
        self.assertEqual(jarvis.last_context_tokens(self._transcript(320000)), 320102)

    def test_sesi_besar_atau_lama_tidak_dilanjutkan(self):
        old_path = jarvis.transcript_path
        try:
            jarvis.transcript_exists = lambda sid: True
            for tokens, age, resumed in ((5000, 0, True), (320000, 0, False), (5000, 10, False)):
                path = self._transcript(tokens, age)
                jarvis.transcript_path = lambda sid, p=path: p
                a = bare_jarvis(self.work)
                a.remember_session(self.work)
                b = bare_jarvis(self.work)
                b.restore_session()
                self.assertEqual(b.session_started, resumed, (tokens, age))
                self.assertEqual(b.session_id == a.session_id, resumed, (tokens, age))
            # batas 0 = selalu dilanjutkan
            jarvis.transcript_path = lambda sid, p=self._transcript(320000, 10): p
            b = bare_jarvis(self.work)
            b.settings.update(resume_max_tokens=0, resume_max_hours=0)
            b.restore_session()
            self.assertTrue(b.session_started)
        finally:
            jarvis.transcript_path = old_path

    def test_tombol_baru(self):
        a = bare_jarvis(self.work)
        said = []
        a.speak = said.append
        a.record = lambda *x, **k: None
        a.prewarm_claude = lambda: None
        a.busy = True
        self.assertFalse(a.ui_new_conversation()["ok"])
        a.busy = False
        old = a.session_id
        self.assertTrue(a.ui_new_conversation()["ok"])
        self.assertNotEqual(a.session_id, old)
        self.assertEqual(said, [])            # tombol: tanpa suara, cukup toast

    def test_simpan_lalu_resume(self):
        a = bare_jarvis(self.work)
        a.remember_session(self.work)
        with open(jarvis.STATE_PATH, encoding="utf-8") as f:
            self.assertEqual(json.load(f)[jarvis.dir_key(self.work)], a.session_id)

        jarvis.transcript_exists = lambda sid: True
        b = bare_jarvis(self.work)
        b.restore_session()
        self.assertEqual((b.session_id, b.session_started), (a.session_id, True))
        cmd = b.claude_cmd(None)
        self.assertEqual(cmd[cmd.index("--resume") + 1], a.session_id)
        self.assertNotIn("--session-id", cmd)

    def test_tanpa_transkrip_mulai_baru(self):
        a = bare_jarvis(self.work)
        a.remember_session(self.work)
        jarvis.transcript_exists = lambda sid: False
        b = bare_jarvis(self.work)
        sid0 = b.session_id
        b.restore_session()
        self.assertEqual((b.session_id, b.session_started), (sid0, False))
        self.assertIn("--session-id", b.claude_cmd(None))

    def test_folder_lain_tidak_ikut(self):
        a = bare_jarvis(self.work)
        a.remember_session(self.work)
        jarvis.transcript_exists = lambda sid: True
        b = bare_jarvis(self.tmp)
        b.restore_session()
        self.assertFalse(b.session_started)

    def test_state_rusak_diabaikan(self):
        with open(jarvis.STATE_PATH, "w", encoding="utf-8") as f:
            f.write("{bukan json")
        b = bare_jarvis(self.work)
        b.restore_session()
        self.assertFalse(b.session_started)
        with open(jarvis.STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({jarvis.dir_key(self.work): "bukan-uuid"}, f)
        b.restore_session()
        self.assertFalse(b.session_started)

    def test_percakapan_baru_mereset(self):
        jarvis.transcript_exists = lambda sid: True
        a = bare_jarvis(self.work)
        a.remember_session(self.work)
        a.restore_session()
        old = a.session_id
        said = []
        a.speak = said.append
        a.record = lambda *x, **k: None
        a.prewarm_claude = lambda: None
        a.reset_conversation()
        self.assertNotEqual(a.session_id, old)
        self.assertFalse(a.session_started)
        self.assertNotIn(jarvis.dir_key(self.work), jarvis.load_state())
        self.assertEqual(said, ["Oke, percakapan baru."])

    def test_dispatch_mengarahkan_perintah(self):
        j = bare_jarvis(self.work)
        j.hold_lock, j.hold_timer, j.hold_notes, j.hold_dur = threading.Lock(), None, [""], 1.0
        j.hold_text = ["percakapan baru"]
        hit = []
        j.reset_conversation = lambda: hit.append(True)
        j.run_turn = lambda *a, **k: self.fail("tidak boleh dikirim ke Claude")
        j.dispatch()
        self.assertEqual(hit, [True])



class TestToolSearch(unittest.TestCase):
    """Konektor aktif: alat MCP ditunda (ENABLE_TOOL_SEARCH=true) dan ToolSearch ikut di --tools."""

    def start(self, **settings):
        captured = {}

        class FakeSession:
            def __init__(self, cmd, cwd, env, key):
                captured.update(cmd=cmd, env=env)
                self.key = key

            def alive(self):
                return True

        old_cls = jarvis.ClaudeSession
        try:
            jarvis.ClaudeSession = FakeSession
            j = bare_jarvis(tempfile.gettempdir(), **settings)
            j.known_servers = set(jarvis.MCP_SERVERS_SEED)
            j.get_session(None)
        finally:
            jarvis.ClaudeSession = old_cls
        cmd = captured["cmd"]
        return cmd[cmd.index("--tools") + 1].split(","), captured["env"]["ENABLE_TOOL_SEARCH"]

    def test_konektor_aktif_alat_ditunda(self):
        tools, env = self.start(claude_connectors=["Canva"])
        self.assertEqual(env, "true")
        self.assertIn("ToolSearch", tools)

    def test_tanpa_konektor_tidak_ditunda(self):
        tools, env = self.start(claude_connectors=[])
        self.assertEqual(env, "false")
        self.assertNotIn("ToolSearch", tools)

    def test_bisa_dimatikan(self):
        tools, env = self.start(claude_connectors=["Canva"], tool_search=False)
        self.assertEqual(env, "false")
        self.assertNotIn("ToolSearch", tools)

    def test_toolsearch_tidak_dobel(self):
        tools, _ = self.start(claude_connectors=["Canva"], claude_tools="Bash,ToolSearch")
        self.assertEqual(tools.count("ToolSearch"), 1)

    def test_all_semua_konektor_diizinkan(self):
        known = set(jarvis.MCP_SERVERS_SEED) | {"windows-mcp"}
        allow, deny = jarvis.connector_rules({"claude_connectors": "all", "connector_deny": ["x"]}, known)
        self.assertEqual(len(allow), len(jarvis.MCP_SERVERS_SEED))
        self.assertIn("mcp__claude_ai_Gmail", allow)
        self.assertNotIn("mcp__windows-mcp", allow)                      # milik Jarvis: tidak disentuh
        self.assertEqual(deny, [f"{p}__x" for p in allow])               # hanya connector_deny, tidak ada yang disembunyikan

    def test_deny_nama_lengkap_tidak_dikalikan(self):
        full = "mcp__claude_ai_TikTok_for_Business__smart_plus_ad_create"
        allow, deny = jarvis.connector_rules({"claude_connectors": "all", "connector_deny": [full]},
                                             set(jarvis.MCP_SERVERS_SEED))
        self.assertEqual(deny, [full])

    def test_settings_asli_muat_di_command_line(self):
        with open(os.path.join(os.path.dirname(jarvis.__file__), "settings.json"), encoding="utf-8") as f:
            real = json.load(f)
        keep = {k: real[k] for k in ("claude_connectors", "connector_deny", "deny_list", "claude_tools") if k in real}
        j = bare_jarvis(tempfile.gettempdir(), **keep)
        j.known_servers = set(jarvis.MCP_SERVERS_SEED)
        cmd = j.claude_cmd(None)
        self.assertLess(jarvis.cmdline_length(cmd), jarvis.cmdline_limit(jarvis.resolve_claude()))

    def test_batas_command_line_ikut_jenis_file(self):
        # claude.exe langsung (CreateProcess) boleh ~32k; lewat claude.cmd (cmd.exe) hanya ~8k
        self.assertEqual(jarvis.cmdline_limit(r"C:\x\claude.exe"), 32000)
        self.assertEqual(jarvis.cmdline_limit(r"C:\x\claude.CMD"), 8000)
        self.assertGreater(jarvis.cmdline_length(["a b", 'c"d']), len("a b") + len('c"d'))

    def test_all_menyalakan_tool_search(self):
        tools, env = self.start(claude_connectors="all")
        self.assertEqual(env, "true")
        self.assertIn("ToolSearch", tools)

    def test_all_cek_status_tidak_pecah_per_huruf(self):
        j = bare_jarvis(tempfile.gettempdir(), claude_connectors="all")
        j.known_servers = set(jarvis.MCP_SERVERS_SEED)
        servers = [{"name": "claude.ai Canva", "status": "connected"},
                   {"name": "claude.ai viewmax", "status": "needs-auth"}]
        sess = type("S", (), {"init": {"mcp_servers": servers}})()
        j.check_connectors(sess, "all")
        logs = [t for tag, t in j.ui.logs if "konektor" in t]
        self.assertEqual(len(logs), 1)
        self.assertIn("viewmax", logs[0])

    def test_konektor_dimatikan_per_folder_diperingatkan(self):
        work = tempfile.mkdtemp()
        cfg = os.path.join(work, "claude.json")
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"projects": {work.replace("\\", "/"): {"disabledMcpServers": ["claude.ai Higgsfield",
                                                                                    "claude.ai Gmail"]}}}, f)
        self.assertEqual(jarvis.disabled_connectors(work, cfg), ["claude.ai Higgsfield", "claude.ai Gmail"])
        self.assertEqual(jarvis.disabled_connectors(tempfile.gettempdir(), cfg), [])
        old = jarvis.CLAUDE_JSON_PATH
        try:
            jarvis.CLAUDE_JSON_PATH = cfg
            j = bare_jarvis(work, claude_connectors="all")
            j.warn_disabled_connectors()
            j.warn_disabled_connectors()                                  # sekali saja
            logs = [t for tag, t in j.ui.logs if "Dimatikan" in t]
            self.assertEqual(len(logs), 1)
            self.assertIn("Gmail, Higgsfield", logs[0])
            k = bare_jarvis(work, claude_connectors=["Canva"])             # tidak dipilih: diam
            k.warn_disabled_connectors()
            self.assertFalse(k.ui.logs)
        finally:
            jarvis.CLAUDE_JSON_PATH = old

    def test_init_kosong_tidak_salah_lapor(self):
        j = bare_jarvis(tempfile.gettempdir(), claude_connectors=["Canva"])
        j.known_servers = set(jarvis.MCP_SERVERS_SEED)
        sess = type("S", (), {"init": {"mcp_servers": []}})()
        j.check_connectors(sess, ["Canva"])
        self.assertFalse([t for tag, t in j.ui.logs if "konektor" in t])



class FakeResp:
    def __init__(self, code, body=None):
        self.status_code, self.ok, self._body = code, 200 <= code < 300, body or {}

    def json(self):
        return self._body


class TestKunci(unittest.TestCase):
    """Menu KUNCI API: registry, server, dan settings.json asli tidak disentuh."""

    def setUp(self):
        self.saved_env, self.saved_settings = {}, []
        self.orig = (jarvis.set_user_env, jarvis.save_settings, jarvis.check_eleven, jarvis.check_groq,
                     jarvis.user_env, jarvis.Jarvis.fetch_credit, jarvis.Jarvis.prepare_acks, jarvis.check_speechify)
        jarvis.set_user_env = lambda n, v: self.saved_env.__setitem__(n, v)
        jarvis.save_settings = lambda s: self.saved_settings.append(dict(s))
        jarvis.check_eleven = lambda k, v: (None, [])
        jarvis.check_groq = lambda k: (None, [])
        jarvis.check_speechify = lambda k, v, m: (None, [])
        jarvis.user_env = lambda n: {"ELEVENLABS_VOICE_ID": "voiceLama"}.get(n)
        jarvis.Jarvis.fetch_credit = jarvis.Jarvis.prepare_acks = lambda self: None
        self.j = bare_jarvis(tempfile.gettempdir(), voice_id="")
        self.j.api_key = "sk_lama_1234"
        self.j.speechify_key = None
        self.j.credit = None

    def tearDown(self):
        (jarvis.set_user_env, jarvis.save_settings, jarvis.check_eleven, jarvis.check_groq,
         jarvis.user_env, jarvis.Jarvis.fetch_credit, jarvis.Jarvis.prepare_acks, jarvis.check_speechify) = self.orig

    def test_pindah_ke_speechify(self):
        self.assertFalse(self.j.apply_keys({"provider": "speechify"})["ok"])          # kunci belum ada
        res = self.j.apply_keys({"provider": "speechify", "speechify_key": "sk_sfy_7777",
                                 "speechify_voice_id": "sfyVoice"})
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.saved_env, {"SPEECHIFY_API_KEY": "sk_sfy_7777"})
        self.assertEqual((self.j.tts_provider(), self.j.tts_ready()), ("speechify", True))
        self.assertEqual(self.saved_settings[-1]["speechify_voice_id"], "sfyVoice")
        self.assertEqual(res["keys"]["speechify"], "••••7777")
        self.assertNotIn("sk_sfy", json.dumps(res["keys"]))
        self.assertTrue(self.j.apply_keys({"provider": "elevenlabs"})["ok"])          # balik lagi
        self.assertEqual(self.j.tts_provider(), "elevenlabs")

    def test_suara_lewat_speechify(self):
        self.j.settings.update(tts_provider="speechify", speechify_voice_id="sfyVoice")
        self.j.speechify_key = "sk_sfy"
        sent = {}

        def post(url, **kw):
            sent.update(url=url, **kw)
            return type("R", (), {"status_code": 200, "content": b"\x01\x00\x02\x00\x03", "text": ""})()
        orig = jarvis.requests.post
        try:
            jarvis.requests.post = post
            audio, rate = self.j.fetch_tts("halo")
        finally:
            jarvis.requests.post = orig
        self.assertEqual(sent["url"], "https://api.speechify.ai/v1/audio/stream")
        self.assertEqual(sent["headers"]["Authorization"], "Bearer sk_sfy")
        self.assertEqual(sent["json"], {"input": "halo", "voice_id": "sfyVoice", "output_format": "pcm_24000",
                                        "model": "simba-3.5", "language": "id-ID"})
        self.assertEqual((list(audio), rate), ([1, 2], jarvis.TTS_RATE))

    def stream_session(self, resp, edge=None):
        """SpeechSession dengan Speechify palsu dan kartu suara palsu. Return (tulisan ke kartu suara, cadangan)."""
        self.j.settings.update(tts_provider="speechify", speechify_voice_id="sfyVoice", fallback_voice=True)
        self.j.speechify_key = "sk_sfy"
        self.j.muted, self.j.tm = False, {}
        written, played = [], []

        class FakeOut:
            def __init__(self, **kw):
                self.kw = kw
            def start(self): pass
            def write(self, data): written.append(data.copy())
            def stop(self): pass
            def close(self): pass
            def abort(self): pass

        orig = (jarvis.sd.OutputStream, jarvis.Jarvis.open_speechify_stream, jarvis.Jarvis.fetch_edge_tts,
                jarvis.SpeechSession._play, jarvis.time.sleep)
        try:
            jarvis.sd.OutputStream = FakeOut
            jarvis.Jarvis.open_speechify_stream = lambda self, text: resp
            jarvis.Jarvis.fetch_edge_tts = lambda self, text: edge
            jarvis.SpeechSession._play = lambda self, a, r: played.append((a, r))
            jarvis.time.sleep = lambda s: None
            sp = jarvis.SpeechSession(self.j, track=True)
            sp.say_answer("Halo, sudah beres.")
            sp.finish()
        finally:
            (jarvis.sd.OutputStream, jarvis.Jarvis.open_speechify_stream, jarvis.Jarvis.fetch_edge_tts,
             jarvis.SpeechSession._play, jarvis.time.sleep) = orig
        return written, played

    def test_speechify_diputar_sambil_diunduh(self):
        import numpy as np
        pcm = np.arange(12000, dtype=np.int16).tobytes()           # 0,5 detik audio
        chunks = [pcm[:4097], pcm[4097:9001], pcm[9001:]]           # potongan ganjil: byte sisa harus disambung

        class Resp:
            closed = False
            def iter_content(self, chunk_size): return iter(chunks)
            def close(self): Resp.closed = True
        written, played = self.stream_session(Resp())
        self.assertGreater(len(written), 1)                          # diputar bertahap, bukan sekaligus
        self.assertEqual(np.concatenate(written).ravel().tobytes(), pcm)
        self.assertIn("voice", self.j.tm)
        self.assertTrue(Resp.closed)
        self.assertEqual(played, [])

    def test_speechify_gagal_pakai_cadangan(self):
        written, played = self.stream_session(None, edge=("audio", 16000))
        self.assertEqual((written, played), ([], [("audio", 16000)]))
        self.assertIn("voice", self.j.tm)

    def test_cek_speechify_membaca_status_server(self):
        check, orig_get = self.orig[7], jarvis.requests.get
        try:
            jarvis.requests.get = lambda url, **kw: FakeResp(401)
            self.assertIn("ditolak", check("sk", "v", "simba-3.5")[0])
            jarvis.requests.get = lambda url, **kw: FakeResp(404)
            self.assertIn("Voice ID", check("sk", "v", "simba-3.5")[0])
            jarvis.requests.get = lambda url, **kw: FakeResp(200, {"models": [{"name": "simba-3.5"}]})
            self.assertEqual(check("sk", "v", "simba-3.5"), (None, []))
        finally:
            jarvis.requests.get = orig_get

    def test_status_disamarkan(self):
        k = self.j.key_status()
        self.assertEqual(k["eleven"], "••••1234")
        self.assertNotIn("sk_lama", json.dumps(k))
        self.assertEqual(k["voice_id"], "voiceLama")

    def test_kosong_tidak_mengubah(self):
        res = self.j.apply_keys({"eleven_key": "", "groq_key": "", "voice_id": "voiceLama"})
        self.assertTrue(res["ok"])
        self.assertEqual((self.saved_env, self.saved_settings), ({}, []))

    def test_ganti_semua_langsung_berlaku(self):
        res = self.j.apply_keys({"eleven_key": " sk_baru_9999 ", "groq_key": "gsk_baru", "voice_id": "voiceBaru"})
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.saved_env, {"ELEVENLABS_API_KEY": "sk_baru_9999", "GROQ_API_KEY": "gsk_baru"})
        self.assertEqual(self.j.api_key, "sk_baru_9999")
        self.assertEqual(self.j.voice_id(), "voiceBaru")
        self.assertEqual(self.saved_settings[-1]["voice_id"], "voiceBaru")
        self.assertEqual(res["keys"]["eleven"], "••••9999")

    def test_kunci_ditolak_tidak_disimpan(self):
        jarvis.check_eleven = lambda k, v: ("API key ElevenLabs ditolak server. Cek lagi kuncinya.", [])
        res = self.j.apply_keys({"eleven_key": "sk_salah"})
        self.assertFalse(res["ok"])
        self.assertEqual(self.saved_env, {})
        self.assertEqual(self.j.api_key, "sk_lama_1234")

    def test_spasi_ditolak(self):
        self.assertFalse(self.j.apply_keys({"eleven_key": "sk a"})["ok"])

    def test_kunci_deepgram_disimpan_dan_disamarkan(self):
        orig = jarvis.check_deepgram
        try:
            jarvis.check_deepgram = lambda k: (None, [])
            res = self.j.apply_keys({"deepgram_key": " dg_rahasia_4321 "})
            self.assertTrue(res["ok"], res)
            self.assertEqual(self.saved_env, {"DEEPGRAM_API_KEY": "dg_rahasia_4321"})
            jarvis.user_env = lambda n: {"DEEPGRAM_API_KEY": "dg_rahasia_4321"}.get(n)
            k = self.j.key_status()
            self.assertEqual(k["deepgram"], "••••4321")
            self.assertNotIn("dg_rahasia", json.dumps(k))                     # kunci utuh tidak ke UI
        finally:
            jarvis.check_deepgram = orig

    def test_kunci_deepgram_ditolak_tidak_disimpan(self):
        orig = jarvis.check_deepgram
        try:
            jarvis.check_deepgram = lambda k: ("API key Deepgram ditolak server. Cek lagi kuncinya.", [])
            res = self.j.apply_keys({"deepgram_key": "dg_salah"})
            self.assertFalse(res["ok"])
            self.assertEqual(self.saved_env, {})
        finally:
            jarvis.check_deepgram = orig

    def test_kunci_speechmatics_disimpan_dan_disamarkan(self):
        orig = jarvis.check_speechmatics
        try:
            jarvis.check_speechmatics = lambda k: (None, [])
            res = self.j.apply_keys({"speechmatics_key": " smx_rahasia_8765 "})
            self.assertTrue(res["ok"], res)
            self.assertEqual(self.saved_env, {"SPEECHMATICS_API_KEY": "smx_rahasia_8765"})
            jarvis.user_env = lambda n: {"SPEECHMATICS_API_KEY": "smx_rahasia_8765"}.get(n)
            k = self.j.key_status()
            self.assertEqual(k["speechmatics"], "••••8765")
            self.assertNotIn("smx_rahasia", json.dumps(k))
            jarvis.check_speechmatics = lambda k: ("API key Speechmatics ditolak server.", [])
            self.saved_env.clear()
            self.assertFalse(self.j.apply_keys({"speechmatics_key": "smx_salah"})["ok"])
            self.assertEqual(self.saved_env, {})
        finally:
            jarvis.check_speechmatics = orig

    def test_cek_speechmatics_membaca_status_server(self):
        orig_get = jarvis.requests.get
        try:
            seen = {}

            def fake(url, **kw):
                seen.update(url=url, auth=kw["headers"]["Authorization"])
                return FakeResp(401)
            jarvis.requests.get = fake
            self.assertIsNotNone(jarvis.check_speechmatics("smx_x")[0])
            self.assertEqual(seen["auth"], "Bearer smx_x")
            self.assertIn("asr.api.speechmatics.com", seen["url"])
            jarvis.requests.get = lambda url, **kw: FakeResp(200, {"jobs": []})
            self.assertEqual(jarvis.check_speechmatics("smx_x"), (None, []))
        finally:
            jarvis.requests.get = orig_get

    def test_cek_deepgram_membaca_status_server(self):
        orig_get = jarvis.requests.get
        try:
            seen = {}

            def fake(url, **kw):
                seen.update(url=url, auth=kw["headers"]["Authorization"])
                return FakeResp(401)
            jarvis.requests.get = fake
            self.assertIsNotNone(jarvis.check_deepgram("dg_x")[0])
            self.assertEqual(seen["auth"], "Token dg_x")
            self.assertIn("api.deepgram.com", seen["url"])
            jarvis.requests.get = lambda url, **kw: FakeResp(200, {"projects": []})
            self.assertEqual(jarvis.check_deepgram("dg_x"), (None, []))
        finally:
            jarvis.requests.get = orig_get

    def test_cek_eleven_membaca_status_server(self):
        orig_get = jarvis.requests.get
        try:
            jarvis.requests.get = lambda url, **kw: FakeResp(401, {"detail": {"status": "invalid_api_key"}})
            self.assertIsNotNone(self.orig[2]("sk", "")[0])
            jarvis.requests.get = lambda url, **kw: (FakeResp(401, {"detail": {"status": "missing_permissions"}})
                                                     if "subscription" in url else FakeResp(404))
            self.assertIn("Voice ID", self.orig[2]("sk", "v")[0])
            jarvis.requests.get = lambda url, **kw: FakeResp(200)
            self.assertEqual(self.orig[2]("sk", "v"), (None, []))
            jarvis.requests.get = lambda url, **kw: FakeResp(401)
            self.assertIsNotNone(self.orig[3]("gsk")[0])
        finally:
            jarvis.requests.get = orig_get



class TestChipModel(unittest.TestCase):
    def shown(self, usage, wanted="sonnet"):
        j = bare_jarvis(tempfile.gettempdir(), claude_model=wanted)
        got = []
        j.ui.model = lambda w, a: got.append(a)
        j.note_model_usage(usage)
        return got[-1], [t for tag, t in j.ui.logs if "PERINGATAN" in t]

    def test_webfetch_haiku_tidak_mengganti_chip(self):
        usage = {"claude-sonnet-5-5": {"outputTokens": 40}, "claude-haiku-5-5": {"outputTokens": 300}}
        self.assertEqual(self.shown(usage), ("claude-sonnet-5-5", []))

    def test_model_benar_benar_beda_tetap_diperingatkan(self):
        actual, warn = self.shown({"claude-haiku-5-5": {"outputTokens": 40}})
        self.assertEqual(actual, "claude-haiku-5-5")
        self.assertTrue(warn)


class TestSahutan(unittest.TestCase):
    """Dipanggil "Jarvis" tanpa perintah: sahut dengan suara dari cache, lalu tunggu perintah."""

    def setUp(self):
        self.j = bare_jarvis(tempfile.gettempdir())
        self.j.active, self.j.await_until = False, 0.0
        self.calls = []
        self.j.reply_wake = lambda: self.calls.append("sahut")
        self.j.beep = lambda: self.calls.append("beep")

    def test_hanya_jarvis_disahut(self):
        self.assertIsNone(self.j.filter_wake("Jarvis."))
        self.assertEqual(self.calls, ["sahut"])
        self.assertGreater(self.j.await_until, time.time())
        self.assertEqual(self.j.filter_wake("buka kalkulator"), "buka kalkulator")   # lanjutan tanpa kata panggil

    def test_jarvis_bangun_disahut_bukan_diabaikan(self):
        self.assertIsNone(self.j.filter_wake("Jarvis, bangun."))
        self.assertEqual(self.calls, ["sahut"])

    def test_perintah_lengkap_langsung_jalan(self):
        self.assertEqual(self.j.filter_wake("Jarvis buka Chrome"), "buka Chrome")
        self.assertEqual(self.calls, ["beep"])

    def test_sudah_aktif_dipanggil_lagi(self):
        self.j.active = True
        self.assertIsNone(self.j.filter_wake("Jarvis"))
        self.assertEqual(self.calls, ["sahut"])


class TestIstirahat(unittest.TestCase):
    """Log 14-11 13:00-13:11: perintah istirahat tidak dikenali dan mode aktif tidak pernah kembali istirahat."""

    def setUp(self):
        self.j = bare_jarvis(tempfile.gettempdir())
        self.j.active, self.j.await_until, self.j.muted = False, 0.0, False
        self.lines, self.said = [], []
        self.j.record_line = lambda kind, detail: self.lines.append(kind)
        self.j.speak = self.said.append
        self.j.reply_wake = lambda: None
        self.j.beep = lambda: None

    def test_perintah_istirahat_dikenali(self):
        for t in ("Oke, kamu boleh istirahat.", "kamu boleh istirahat dulu.", "Jarvis, kamu boleh istirahat dulu.",
                  "Kamu istirahat dulu Jarvis, jangan dengerin aku.", "Oke, ini lagi gue cek dulu. Kamu istirahat dulu.",
                  "istirahat", "Jangan dengerin aku dulu ya."):
            self.assertTrue(jarvis.is_rest_command(t), t)
        for t in ("kenapa mode istirahat nggak jalan", "cek fitur istirahat di kode", "buka kalkulator",
                  "Berarti kalo kamu istirahat kamu ga abaikan semua perintah aku ya.", "Jarvis"):
            self.assertFalse(jarvis.is_rest_command(t), t)

    def test_aktif_lalu_disuruh_istirahat(self):
        self.assertEqual(self.j.filter_wake("Jarvis, buka kalkulator"), "buka kalkulator")
        self.assertTrue(self.j.active)
        self.assertIsNone(self.j.filter_wake("Jarvis, kamu boleh istirahat dulu."))
        self.assertFalse(self.j.active)
        self.assertEqual(self.said, ["Baik, istirahat."])
        self.assertIsNone(self.j.filter_wake("Barusan itu gue ngomong."))      # sekarang diabaikan
        self.assertEqual(self.lines[-1], "DIABAIKAN")

    def test_otomatis_istirahat_setelah_diam(self):
        self.j.filter_wake("Jarvis, buka kalkulator")
        self.assertEqual(self.j.filter_wake("tutup lagi"), "tutup lagi")     # masih dalam batas waktu
        self.j.last_active = time.time() - 91
        self.assertIsNone(self.j.filter_wake("Barusan itu gue ngomong."))
        self.assertFalse(self.j.active)
        self.assertEqual(self.lines[-2:], ["ISTIRAHAT", "DIABAIKAN"])

    def test_tidak_istirahat_selama_bicara_atau_batas_nol(self):
        self.j.filter_wake("Jarvis, buka kalkulator")
        self.j.last_active = time.time() - 500
        self.j.muted = True
        self.assertFalse(self.j.idle_expired())
        self.j.muted = False
        self.j.settings["active_idle_sec"] = 0
        self.assertFalse(self.j.idle_expired())

    def test_giliran_selesai_mengulang_hitungan(self):
        self.j.active, self.j.last_active = True, time.time() - 500
        self.j.touch_active()
        self.assertFalse(self.j.idle_expired())

    def test_istirahat_saat_sudah_istirahat_tidak_ke_claude(self):
        self.assertIsNone(self.j.filter_wake("Jarvis, istirahat dulu"))
        self.assertFalse(self.j.active)

    def test_tanpa_audio_atau_dimatikan_pakai_beep(self):
        j = bare_jarvis(tempfile.gettempdir(), wake_reply=False)
        j.wake_acks = [("audio", 16000)]
        beeps = []
        j.beep = lambda: beeps.append(1)
        j.reply_wake()
        k = bare_jarvis(tempfile.gettempdir())
        k.wake_acks = []
        k.beep = lambda: beeps.append(1)
        k.reply_wake()
        self.assertEqual(beeps, [1, 1])

    def test_sahutan_diputar_lewat_sesi_suara(self):
        played = []
        orig = jarvis.SpeechSession
        try:
            class FakeSp:
                def __init__(self, app): pass
                def play_ack(self, audio, rate): played.append((audio, rate))
                def finish(self): pass
            jarvis.SpeechSession = FakeSp
            j = bare_jarvis(tempfile.gettempdir())
            j.wake_acks = [("a", 1), ("b", 2)]
            j.reply_wake(); j.reply_wake(); j.reply_wake()
        finally:
            jarvis.SpeechSession = orig
        self.assertEqual(played, [("a", 1), ("b", 2), ("a", 1)])      # bergantian


class TestSpeechmatics(unittest.TestCase):
    """Pengenal suara Speechmatics batch (uji 14-11: 8/8 rekaman benar, Groq 5/8)."""

    class Sess:
        def __init__(self, polls):
            self.polls, self.posted = list(polls), {}

        def post(self, url, **kw):
            self.posted = dict(url=url, cfg=json.loads(kw["data"]["config"]), auth=kw["headers"]["Authorization"])
            return FakeResp(201, {"id": "job1"})

        def get(self, url, **kw):
            code, text = self.polls.pop(0)
            r = FakeResp(code)
            r.text = text
            return r

    def run_smx(self, polls, key="smx_k"):
        old = (jarvis._smx_session, jarvis.user_env, jarvis.SMX_POLL_SEC)
        sess = self.Sess(polls)
        jarvis._smx_session, jarvis.SMX_POLL_SEC = sess, 0
        jarvis.user_env = lambda n: key if n == "SPEECHMATICS_API_KEY" else None
        try:
            return jarvis.transcribe_speechmatics(np.zeros(16000, np.float32), dict(jarvis.DEFAULTS)), sess
        finally:
            jarvis._smx_session, jarvis.user_env, jarvis.SMX_POLL_SEC = old

    def test_hasil_teks_dan_konfigurasi(self):
        segs, sess = self.run_smx([(404, ""), (404, ""), (200, "Kucing aku namanya Sambo.\n")])
        self.assertEqual([s.text for s in segs], ["Kucing aku namanya Sambo."])
        cfg = sess.posted["cfg"]["transcription_config"]
        self.assertEqual((cfg["language"], cfg["operating_point"]), ("id", "enhanced"))
        jv = [v for v in cfg["additional_vocab"] if v["content"].lower() == "jarvis"]
        self.assertTrue(jv and "sounds_like" in jv[0])
        self.assertEqual(sess.posted["auth"], "Bearer smx_k")

    def test_kosong_berarti_tidak_ada_ucapan(self):
        segs, _ = self.run_smx([(200, "  \n")])                 # dentuman keyboard: tidak mengarang teks
        self.assertEqual(segs, [])

    def test_tanpa_kunci_gagal(self):
        with self.assertRaises(RuntimeError):
            self.run_smx([], key=None)

    def test_gagal_pakai_cadangan_groq(self):
        j = bare_jarvis(tempfile.gettempdir(), stt_engine="speechmatics")
        logs = []
        j.log = lambda t, tag="sys": logs.append(t)
        old = (jarvis.transcribe_speechmatics, jarvis.transcribe_groq, jarvis.user_env)
        jarvis.transcribe_speechmatics = lambda a, s: (_ for _ in ()).throw(RuntimeError("HTTP 500"))
        jarvis.transcribe_groq = lambda a, s: [types.SimpleNamespace(text="dari groq", avg_logprob=0, no_speech_prob=0)]
        jarvis.user_env = lambda n: "gsk" if n == "GROQ_API_KEY" else None
        try:
            segs = j.transcribe(np.zeros(16000, np.float32))
        finally:
            jarvis.transcribe_speechmatics, jarvis.transcribe_groq, jarvis.user_env = old
        self.assertEqual(segs[0].text, "dari groq")
        self.assertTrue(any("Speechmatics gagal" in t for t in logs))

    def _toggle(self, engine, keys):
        j = bare_jarvis(tempfile.gettempdir(), stt_engine=engine)
        j.log = lambda *a, **k: None
        saved, shown = [], []
        j.ui.stt = lambda e: shown.append(e)
        old = (jarvis.save_settings, jarvis.user_env)
        jarvis.save_settings = lambda s: saved.append(s["stt_engine"])
        jarvis.user_env = lambda n: "k" if n in keys else None
        try:
            return j.toggle_stt(), j.settings["stt_engine"], saved, shown
        finally:
            jarvis.save_settings, jarvis.user_env = old

    def test_tombol_stt_bolak_balik(self):
        keys = {"GROQ_API_KEY", "SPEECHMATICS_API_KEY"}
        r, now, saved, shown = self._toggle("speechmatics", keys)
        self.assertEqual((r["engine"], now, saved, shown), ("groq", "groq", ["groq"], ["groq"]))
        r, now, _, _ = self._toggle("groq", keys)
        self.assertEqual((r["engine"], r["error"], now), ("speechmatics", None, "speechmatics"))

    def test_tombol_stt_tanpa_kunci_tidak_ganti(self):
        r, now, saved, _ = self._toggle("groq", {"GROQ_API_KEY"})
        self.assertEqual((r["engine"], now, saved), ("groq", "groq", []))
        self.assertIn("Speechmatics", r["error"])

    def test_pengaturan_menerima_speechmatics(self):
        import ui_web
        self.assertIn("speechmatics", [k for k, _ in ui_web.STT_ENGINES])


class TestBacakan(unittest.TestCase):
    """Log 14-11 00:14: "bacakan selamat ulang tahunnya" tetap diringkas jadi satu kalimat 12 kata."""

    def test_deteksi_permintaan_bacakan(self):
        for t in ("Oke kamu bacakan selamat ulang tahunnya saja", "Baca semua maksudnya, ucapannya",
                  "bacain dong isinya", "ucapkan kalimat itu", "coba baca keras paragrafnya"):
            self.assertTrue(jarvis.is_read_aloud(t), t)
        for t in ("buka folder proyek", "kamu sudah baca emailnya?", "Membaca itu penting", "pembacaan hasil"):
            self.assertFalse(jarvis.is_read_aloud(t), t)

    def test_batas_suara_dilonggarkan_saat_bacakan(self):
        app = types.SimpleNamespace(settings=dict(jarvis.DEFAULTS), tts_ready=lambda: True)
        self.assertEqual(jarvis.SpeechSession(app).answer_budget, jarvis.DEFAULTS["speech_cap_chars"])
        self.assertEqual(jarvis.SpeechSession(app, read_aloud=True).answer_budget,
                         jarvis.DEFAULTS["read_aloud_max_chars"])

    def test_pengingat_bacakan_menggantikan_batas_12_kata(self):
        self.assertNotIn("12 kata", jarvis.READ_ALOUD_REMINDER)
        self.assertIn("utuh", jarvis.READ_ALOUD_REMINDER)
        self.assertIn("PENGECUALIAN", jarvis.SYSTEM_PROMPT)


class TestPanggilanJarvis(unittest.TestCase):
    """Log 13-11 23:28: "Jaro Pies." diabaikan sebagai panggilan."""

    def test_kata_panggil_terpecah_dua(self):
        self.assertEqual(jarvis.strip_wake_word("Jar vis, buka chrome", "jarvis"), "buka chrome")
        self.assertEqual(jarvis.strip_wake_word("Jaro vis.", "jarvis"), "")
        self.assertIsNone(jarvis.strip_wake_word("jadi bisa begitu", "jarvis"))
        self.assertIsNone(jarvis.strip_wake_word("jam berapa sekarang", "jarvis"))

    def test_koreksi_jaro_pies(self):
        text, _ = jarvis.apply_corrections("Jaro Pies.")
        self.assertEqual(jarvis.strip_wake_word(text, "jarvis"), "")

    def _recheck(self, text, english, secs=1.0, active=False, engine="groq"):
        j = bare_jarvis(tempfile.gettempdir(), stt_engine=engine)
        j.active, j.pending = active, []
        j.log = lambda *a, **k: None
        lines, calls, clips = [], [], []
        j.record_line = lambda kind, detail: lines.append(kind)
        j.save_heard = lambda audio, t: None
        old = jarvis.transcribe_groq

        def fake(audio, settings, timeout=20):
            calls.append(settings.get("whisper_language"))
            clips.append(len(audio) / jarvis.MIC_RATE)
            return [types.SimpleNamespace(text=english, avg_logprob=-0.2, no_speech_prob=0.0)]
        jarvis.transcribe_groq = fake
        try:
            tail = jarvis.end_silence_blocks(j.settings) * jarvis.BLOCK / jarvis.MIC_RATE   # jeda diam di akhir
            out = j.recheck_wake(np.zeros(int((secs + tail) * jarvis.MIC_RATE), dtype=np.float32), text)
        finally:
            jarvis.transcribe_groq = old
        self.clips = clips
        return out, calls, lines

    def test_cek_ulang_jangan_peace_jadi_panggilan(self):
        out, calls, lines = self._recheck("Jangan, peace.", "Jarvis.")
        self.assertEqual(out, "Jarvis.")
        self.assertEqual(calls, ["en"])
        self.assertEqual(lines, ["CEK ULANG"])

    def test_cek_ulang_bukan_panggilan_teks_asli(self):
        out, calls, lines = self._recheck("Terima kasih.", "Thank you.")
        self.assertEqual(out, "Terima kasih.")
        self.assertEqual(lines, [])

    def test_cek_ulang_dilewati_kalau_aktif_atau_panjang(self):
        self.assertEqual(self._recheck("Jangan, peace.", "Jarvis.", active=True)[1], [])
        self.assertEqual(self._recheck("tolong buka folder proyek sekarang", "Jarvis.", secs=13)[1], [])
        self.assertEqual(self._recheck("Jarvis.", "Jarvis.")[1], [])            # sudah terbaca

    def test_cek_ulang_jeda_diam_tidak_dihitung(self):
        # log 13-11 23:41: "Terima kasih." (suara ~1 dtk + jeda 1,2 dtk) dulu tidak pernah dicek ulang
        out, calls, _ = self._recheck("Terima kasih.", "Thank you.", secs=1.0)
        self.assertEqual(calls, ["en"])
        tail = jarvis.end_silence_blocks(jarvis.DEFAULTS) * jarvis.BLOCK / jarvis.MIC_RATE
        self.assertAlmostEqual(self.clips[0], 1.0 + tail, places=2)           # utuh, bukan potongan awal

    def test_cek_awal_kalimat_jarvis_hilang(self):
        # log 13-11 23:41: "Jarvis, coba carikan aku kopi" terbaca "Coba carikan aku copy."
        out, calls, lines = self._recheck("Coba carikan aku copy.", "Jarvis, try", secs=3.0)
        self.assertEqual(out, "Jarvis, Coba carikan aku copy.")
        self.assertEqual(jarvis.strip_wake_word(out, "jarvis"), "Coba carikan aku copy.")
        self.assertAlmostEqual(self.clips[0], jarvis.RECHECK_HEAD_SEC, places=2)   # hanya awal kalimat
        self.assertEqual(lines, ["CEK ULANG"])

    def test_cek_awal_kalimat_bukan_panggilan(self):
        out, _, lines = self._recheck("Coba carikan aku copy.", "Try to find", secs=3.0)
        self.assertEqual(out, "Coba carikan aku copy.")
        self.assertEqual(lines, [])

    def test_dentuman_meja_tidak_dianggap_suara(self):
        # log 13-11 23:47-23:55: dentuman ketikan (<100 Hz) terekam lalu jadi "Terima kasih." palsu
        t = np.arange(jarvis.BLOCK) / jarvis.MIC_RATE
        thump = 0.05 * np.sin(2 * np.pi * 60 * t).astype(np.float32)        # keras tapi rendah
        voice = 0.03 * np.sin(2 * np.pi * 300 * t).astype(np.float32)       # pelan tapi di frekuensi suara
        self.assertLess(jarvis.voice_rms(thump), jarvis.MIN_THRESHOLD / 2)   # sisa kebocoran FFT blok 30 ms
        self.assertLess(jarvis.voice_rms(thump), float(np.sqrt(np.mean(thump ** 2))) / 5)
        self.assertGreater(jarvis.voice_rms(voice), jarvis.MIN_THRESHOLD)
        self.assertAlmostEqual(jarvis.voice_rms(voice), float(np.sqrt(np.mean(voice ** 2))), places=3)

    def test_mulai_selalu_istirahat(self):
        # permintaan user 13-11: tiap start harus dipanggil "Jarvis" dulu, baru menyahut "Iya bos?"
        import inspect
        src = inspect.getsource(jarvis.Jarvis.__init__)
        self.assertIn("self.active = False", src)

if __name__ == "__main__":
    unittest.main(verbosity=2)
