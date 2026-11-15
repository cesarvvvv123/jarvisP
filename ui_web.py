"""UI Jarvis berbasis HTML (pywebview). Jalankan:  python jarvis.py

Jembatan:
- Python -> JS: window.jarvis.setState(nama, data), window.jarvis.setLevel(0..1), window.jarvis.setMini(bool)
- JS -> Python (js_api): onPushToTalk(down), onCancel(), onOpenSettings(), onMini(), onClose(),
  saveSettings(obj), plus getSettings(), onWake(on), onReady()
Keadaan tampilan diturunkan dari status dan log yang sudah dikirim inti Jarvis (tanpa mengubah logikanya).
"""
import json
import os
import re
import threading
import time

import webview

APP_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(APP_DIR, "ui", "index.html")
FULL_SIZE, MINI_SIZE = (520, 780), (200, 200)

VOICE_MODELS = [("eleven_v4_turbo", "v4 Turbo"), ("eleven_v3_conversational", "v3 Conversational"),
                ("eleven_v3", "v3")]
STT_ENGINES = [("small", "Whisper small (lokal)"), ("base", "Whisper base (lokal)"),
               ("groq", "Groq large-v3-turbo (online, fallback lokal)"),
               ("speechmatics", "Speechmatics enhanced (online, lebih akurat, cadangan Groq)")]

# status teks dari inti Jarvis -> nama keadaan tampilan
STATUS_MAP = [
    ("berbicara", "speaking"),
    ("memproses", "processing"),
    ("merekam", "listening"), ("mengenali suara", "listening"), ("masih menunggu lanjutan", "listening"),
    ("mendengarkan...", "listening"),
]


def list_mics():
    try:
        import sounddevice as sd
        names = []
        for d in sd.query_devices():
            if d.get("max_input_channels", 0) > 0 and d["name"] not in names:
                names.append(d["name"])
        return names
    except Exception:
        return []


class WebUI:
    """Objek `ui` untuk jarvis.Jarvis yang menggambar lewat pywebview."""

    def __init__(self):
        self.window = None
        self.app = None
        self.ready = False
        self.pending_js = []
        self.lock = threading.Lock()
        self.state = "idle"
        self.fallback = False          # suara cadangan dipakai pada giliran ini -> keadaan "warning"
        self.mini = False
        self.last_level = 0.0
        self.data = {"transcript": "", "speech": "", "lines": [], "meta": "", "time": "—", "credit": None,
                     "project": "", "projectPath": "", "model": "", "wake": True, "hint": "",
                     "hotkey": "F9", "browser": False, "screen": False, "clip": True, "desktop": False}

    # ----- jembatan ke JS -----
    def js(self, code):
        with self.lock:
            if not self.ready:
                self.pending_js.append(code)
                return
        try:
            self.window.evaluate_js(code)
        except Exception:
            pass

    def on_loaded(self):
        with self.lock:
            self.ready = True
            todo, self.pending_js = self.pending_js, []
        shape_window(self.window, self.mini)
        for code in todo:
            try:
                self.window.evaluate_js(code)
            except Exception:
                pass
        self.push()

    def push(self):
        name = "warning" if (self.fallback and self.state in ("speaking", "processing")) else self.state
        self.js(f"window.jarvis && window.jarvis.setState({json.dumps(name)}, {json.dumps(self.data)})")

    # ----- antarmuka yang dipakai jarvis.Jarvis -----
    def attach(self, app):
        self.app = app
        s = app.settings
        self.data.update(model=s.get("claude_model") or "bawaan", wake=bool(s.get("wake_mode")),
                         hotkey=s.get("hotkey", "F9"), browser=s.get("browser_mode") == "chrome",
                         screen=bool(s.get("screen_enabled")), clip=bool(s.get("clipboard_enabled", True)),
                         desktop=s.get("desktop_control") == "on", stt=s.get("stt_engine") or "local")

    def log(self, text, tag="sys"):
        d, changed = self.data, True
        if tag == "you":
            t = re.sub(r"^>\s*(\(digabung\)\s*)?", "", text)
            d.update(transcript=t, speech="", lines=[], meta="")
        elif tag == "claude":
            d["speech"] = text
        elif tag == "layar":
            d["lines"] = d["lines"] + [{"t": ln.strip(" -•"), "dot": "ok"} for ln in text.splitlines() if ln.strip()]
        elif tag == "ask":
            d["lines"] = d["lines"] + [{"t": text, "dot": "info"}]
        elif tag == "err":
            d["lines"] = d["lines"] + [{"t": text[:160], "dot": "warn"}]
        elif tag == "say":
            m = re.match(r"\[suara (cadangan )?(\d+) karakter\]", text)
            if m:
                d["meta"] = f"suara {m.group(2)} karakter" + (" · cadangan" if m.group(1) else "")
                if m.group(1):
                    self.fallback = True
            m = re.search(r"total ([\d.]+)s", text)
            if text.startswith("[waktu]") and m:
                d["time"] = f"{m.group(1)} dtk"
            elif not m and not text.startswith("[suara"):
                changed = False
        else:
            changed = False
        if changed:
            self.push()

    def status(self, text):
        state = "idle"
        for key, name in STATUS_MAP:
            if text.startswith(key):
                state = name
                break
        if text.startswith("menunggu jawaban"):
            self.data["hint"] = "Jawab “ya” atau “tidak”"
        elif text.startswith("memuat"):
            self.data["hint"] = "Memuat model pengenal suara…"
        else:
            self.data["hint"] = ""
        if state == "idle":
            self.fallback = False
        if state != self.state or state == "idle":
            if state == "listening" and self.state == "idle":
                self.data.update(transcript="", speech="", lines=[], meta="")
            self.state = state
            self.push()

    def folder(self, name, path):
        self.data.update(project=name, projectPath=path)
        self.push()

    def wake_checked(self, on):
        self.data["wake"] = bool(on)
        self.push()

    def recording(self, on):
        pass                                   # keadaan "merekam" datang lewat status()

    def level(self, value):
        now = time.time()
        if now - self.last_level < 0.03:       # ~30 kali per detik
            return
        self.last_level = now
        self.js(f"window.jarvis && window.jarvis.setLevel({value:.3f})")

    def credit(self, value):
        self.data["credit"] = value
        self.push()

    def model(self, wanted, actual):
        """Chip MODEL: nama model asli dari modelUsage kalau sudah ada, selain itu setelan yang dipilih."""
        self.data["model"] = actual.replace("claude-", "") if actual else wanted
        self.data["modelTitle"] = f"diminta: {wanted}" + (f" · asli: {actual}" if actual else " · belum dipakai")
        self.push()

    def browser(self, on):
        """Chip BROWSER: cyan saat aktif, abu-abu saat mati."""
        self.data["browser"] = bool(on)
        self.push()

    def desktop(self, on):
        """Chip KOMPUTER: cyan saat kontrol komputer aktif, abu-abu saat mati."""
        self.data["desktop"] = bool(on)
        self.push()

    def stt(self, engine):
        """Chip pengenal suara (groq / speechmatics / local)."""
        self.data["stt"] = engine or "local"
        self.push()

    def capture(self, screen, clip):
        """Chip LAYAR dan CLIPBOARD: cyan saat diizinkan, redup saat mati."""
        self.data.update(screen=bool(screen), clip=bool(clip))
        self.push()

    def call_later(self, ms, fn):
        threading.Timer(ms / 1000, fn).start()

    def on_top(self, on):
        if self.window:
            try:
                self.window.on_top = bool(on)
            except Exception:
                pass

    def hotkey_changed(self, key):
        self.data["hotkey"] = key
        self.push()

    def set_mini(self, on):
        self.mini = bool(on)
        w, h = MINI_SIZE if self.mini else FULL_SIZE
        self.window.resize(w, h)
        self.js(f"window.jarvis && window.jarvis.setMini({json.dumps(self.mini)})")
        threading.Timer(0.15, lambda: shape_window(self.window, self.mini)).start()   # setelah ukuran baru berlaku


class Api:
    """Fungsi yang bisa dipanggil JS lewat window.pywebview.api.* (atribut privat tidak diekspos)."""

    def __init__(self, ui):
        self._ui = ui

    def _app(self):
        return self._ui.app

    def onReady(self):
        self._ui.on_loaded()

    def onPushToTalk(self, down):
        app = self._app()
        if not app:
            return
        if down:
            app.start_rec()
        else:
            app.stop_rec()

    def onCancel(self):
        if self._app():
            self._app().cancel()

    def onWake(self, on):
        if self._app():
            self._app().set_wake(bool(on))

    def onCycleModel(self):
        app = self._app()
        return app.cycle_model() if app else None

    def onToggleStt(self):
        app = self._app()
        return app.toggle_stt() if app else None

    def onNewConversation(self):
        app = self._app()
        return app.ui_new_conversation() if app else None

    def onToggleBrowser(self):
        app = self._app()
        return app.toggle_browser() if app else None

    def onToggleDesktop(self):
        app = self._app()
        return app.toggle_desktop() if app else None

    def onToggleScreen(self):
        app = self._app()
        return app.toggle_capture("screen_enabled") if app else None

    def onToggleClipboard(self):
        app = self._app()
        return app.toggle_capture("clipboard_enabled") if app else None

    def onOpenSettings(self):
        return self.getSettings()

    def getSettings(self):
        app = self._app()
        s = app.settings if app else {}
        return {
            "tts_model_id": s.get("tts_model_id", "eleven_v4_turbo"),
            "fallback_voice": bool(s.get("fallback_voice", True)),
            "speak_details": bool(s.get("speak_details", False)),
            "mic_device": s.get("mic_device") or "",
            "stt": s.get("whisper_model", "small") if s.get("stt_engine", "local") == "local"
            else s.get("stt_engine"),
            "end_silence_ms": int(s.get("end_silence_ms", 1000)),
            "merge_window_ms": int(s.get("merge_window_ms", 0)),
            "ack_enabled": bool(s.get("ack_enabled", True)),
            "wake_reply": bool(s.get("wake_reply", True)),
            "run_mode": s.get("run_mode", "direct"),
            "claude_model": s.get("claude_model") or "sonnet",
            "projects": [{"name": n, "path": p} for n, p in (s.get("projects") or {}).items()],
            "always_on_top": bool(s.get("always_on_top", False)),
            "browser_mode": s.get("browser_mode") or "off",
            "browser_confirm": bool(s.get("browser_confirm", False)),
            "desktop_control": s.get("desktop_control") or "off",
            "screen_enabled": bool(s.get("screen_enabled", False)),
            "clipboard_enabled": bool(s.get("clipboard_enabled", True)),
            "keys": app.key_status() if app else {"provider": "elevenlabs", "eleven": "", "voice_id": "",
                                                  "speechify": "", "speechify_voice_id": "", "groq": "",
                                                  "deepgram": "", "speechmatics": ""},
            "options": {"voice_models": VOICE_MODELS, "stt": STT_ENGINES, "mics": list_mics()},
        }

    def saveKeys(self, obj):
        app = self._app()
        if not app:
            return {"ok": False, "error": "Jarvis belum siap."}
        return app.apply_keys(obj)

    def saveSettings(self, obj):
        app = self._app()
        if not app:
            return {"ok": False, "error": "Jarvis belum siap."}
        new = dict(obj or {})
        stt = new.pop("stt", "small")
        if stt in ("groq", "speechmatics"):
            new["stt_engine"] = stt
        else:
            new["stt_engine"], new["whisper_model"] = "local", stt
        err = app.apply_settings(new)
        return {"ok": err is None, "error": err}

    def onMini(self):
        self._ui.set_mini(not self._ui.mini)

    def onClose(self):
        app = self._app()
        if app:
            app.shutdown()
        self._ui.window.destroy()


CORNER_PX = 18   # radius sudut jendela penuh (sama dengan border-radius .win di index.html)


def shape_window(window, circle):
    """Potong bentuk jendela di Windows: sudut membulat (penuh) atau lingkaran (mini). Di luar potongan
    benar-benar desktop. Perlu karena latar transparan WebView2 di pywebview tetap tergambar abu-abu."""
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = window.native.Handle.ToInt64()
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        r = wintypes.RECT()
        if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r)):
            return
        w, h = r.right - r.left, r.bottom - r.top
        if circle:
            rgn = gdi32.CreateEllipticRgn(0, 0, w + 1, h + 1)
        else:
            d = round(2 * CORNER_PX * w / FULL_SIZE[0])        # ikut skala DPI
            rgn = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, d, d)
        user32.SetWindowRgn(wintypes.HWND(hwnd), rgn, True)    # region jadi milik jendela, jangan dihapus
    except Exception:
        pass


def make_window(ui, api, on_top=False):
    win = webview.create_window(
        "Jarvis", url=INDEX, js_api=api, width=FULL_SIZE[0], height=FULL_SIZE[1],
        resizable=False, frameless=True, easy_drag=False, on_top=on_top,
        transparent=True, text_select=False,
    )
    ui.window = win
    return win


def run(core):
    ui = WebUI()
    api = Api(ui)
    settings = core.load_settings()
    make_window(ui, api, on_top=bool(settings.get("always_on_top")))

    def start():
        core.Jarvis(ui)                # inti berjalan di thread sendiri; tampilan diperbarui lewat evaluate_js

    webview.start(start)
