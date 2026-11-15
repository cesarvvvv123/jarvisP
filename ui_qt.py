"""UI Jarvis berbasis HTML di jendela Qt (PySide6 + QtWebEngine) yang benar-benar transparan per piksel.

Jalankan:  python jarvis.py          (pakai ui_qt bila PySide6 terpasang)
           python jarvis.py --webview-ui   (paksa UI lama pywebview: ui_web.py)

Isi tampilan (ui/index.html) dan logika status sama dengan ui_web.py; yang beda hanya jendelanya:
- Jendela tanpa bingkai + WA_TranslucentBackground, latar halaman transparan -> hanya HUD yang terlihat.
- Di Windows, piksel transparan tidak meneruskan klik ke desktop dengan sendirinya. Karena itu halaman
  mengirim kotak-kotak area yang bisa disentuh (orb, teks, dock, dst.), lalu Python menyalakan
  WS_EX_TRANSPARENT (klik tembus) saat kursor ada di luar kotak itu.
- VERSI: pakai PySide6 6.8.3 (LTS):  python -m pip install "PySide6==6.8.3"
  PySide6 6.12.0 (QtWebEngine) membocorkan RAM renderer selama animasi CSS jalan + halaman di-update
  (~10 MB/detik, sampai 5 GB). Di 6.8.3 diuji datar ~50 MB. Versi lain dicatat ke logs/jarvis_ui_qt.log.
- Jembatan JS <-> Python lewat QWebChannel. Shim yang disuntikkan membuat window.pywebview.api.* dan event
  "pywebviewready" tetap ada, jadi index.html tidak perlu tahu jendelanya Qt atau pywebview.
"""
import ctypes
import json
import os
import sys
import threading
import traceback

from PySide6.QtCore import QFile, QIODevice, QObject, QPoint, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QCursor, QGuiApplication
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

import ui_web
from ui_web import FULL_SIZE, MINI_SIZE, Api, WebUI

APP_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(APP_DIR, "ui", "index.html")
LOG = os.path.join(APP_DIR, "logs", "jarvis_ui_qt.log")
STATE = os.path.join(APP_DIR, "cache", "ui_qt.json")     # ukuran mini + posisi jendela per mode
MINI_MIN, MINI_MAX, MINI_STEP = 120, 520, 20


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass

API_METHODS = [n for n in dir(Api) if not n.startswith("_") and callable(getattr(Api, n))]

GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_LAYERED = -20, 0x20, 0x80000
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10


def _log(text):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n")
    except Exception:
        pass


def _qwebchannel_js():
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if not f.open(QIODevice.ReadOnly):
        raise RuntimeError("qwebchannel.js tidak ditemukan di resource Qt")
    try:
        return bytes(f.readAll()).decode("utf-8")
    finally:
        f.close()


SHIM_JS = r"""
(function () {
  if (window.__jarvisQt) return;
  window.__jarvisQt = true;
  const METHODS = %(methods)s;
  const waiting = {};
  let seq = 0, bridge = null;
  window.__qtResolve = (id, value) => { const w = waiting[id]; if (w) { delete waiting[id]; w(value); } };

  // seret jendela dari elemen .pywebview-drag-region, baru mulai setelah mouse bergeser sedikit
  // supaya klik dan klik-dua-kali (mode mini) tetap jalan
  let press = null;
  window.addEventListener("mousedown", (e) => {
    const t = e.target.closest ? e.target : null;
    const inMini = document.body.classList.contains("mini");
    press = (e.button === 0 && t && t.closest(".pywebview-drag-region") && (inMini || !t.closest(".core")))
      ? { x: e.screenX, y: e.screenY } : null;      // inti orb (mode penuh) = tombol bicara, bukan seret
  }, true);

  // mode mini: scroll di atas orb = perbesar / perkecil
  window.addEventListener("wheel", (e) => {
    if (!document.body.classList.contains("mini") || !bridge) return;
    e.preventDefault();
    bridge.miniWheel(e.deltaY < 0 ? 1 : -1);
  }, { passive: false, capture: true });
  const fitMini = () => document.documentElement.style.setProperty(
    "--mscale", (Math.min(innerWidth, innerHeight) / 360 * 0.98).toFixed(4));
  window.addEventListener("resize", fitMini);
  fitMini();
  window.addEventListener("mousemove", (e) => {
    if (!press || !(e.buttons & 1)) { press = null; return; }
    if (Math.abs(e.screenX - press.x) + Math.abs(e.screenY - press.y) > 3) {
      press = null;
      if (bridge) bridge.startDrag();
    }
  }, true);
  window.addEventListener("mouseup", () => { press = null; }, true);

  // kotak area yang boleh disentuh; di luar ini klik tembus ke desktop
  const HIT = ".titlebar, .orb, .talk .heard:not(:empty), .talk .speech:not(:empty), .talk .lines:not(:empty), " +
              ".talk .meta:not(:empty), .dock, .stats, .toast.show, .settings, body.mini .miniwrap";
  let lastHit = "";
  function sendHit() {
    if (!bridge) return;
    const r = [];
    document.querySelectorAll(HIT).forEach((el) => {
      const b = el.getBoundingClientRect();
      if (b.width > 0 && b.height > 0 && getComputedStyle(el).display !== "none")
        r.push([Math.floor(b.left), Math.floor(b.top), Math.ceil(b.width), Math.ceil(b.height)]);
    });
    const s = JSON.stringify(r);
    if (s !== lastHit) { lastHit = s; bridge.setHitRects(s); }
  }
  setInterval(sendHit, 250);

  function boot() {
    document.documentElement.classList.add("qt");
    new QWebChannel(qt.webChannelTransport, (ch) => {
      bridge = ch.objects.bridge;
      const api = {};
      METHODS.forEach((name) => {
        api[name] = (...args) => new Promise((resolve) => {
          const id = ++seq;
          waiting[id] = resolve;
          bridge.call(name, JSON.stringify(args), id);
        });
      });
      window.pywebview = { api, platform: "qt" };
      sendHit();
      window.dispatchEvent(new Event("pywebviewready"));
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
"""


class Bridge(QObject):
    """Objek yang dilihat JS lewat QWebChannel. Semua slot jalan di thread utama Qt."""

    runJs = Signal(str)          # dipancarkan dari thread mana pun -> dijalankan di thread utama
    modeReq = Signal(bool)       # True = mini
    onTopReq = Signal(bool)
    quitReq = Signal()

    def __init__(self, win, api):
        super().__init__()
        self._win = win
        self._api = api
        self.state = load_state()
        self.cur_mini = False
        self.runJs.connect(self._run_js)
        self.modeReq.connect(self._apply_mode)
        self.onTopReq.connect(self._on_top)
        self.quitReq.connect(self._quit)

    def mini_size(self):
        n = int(self.state.get("mini_size") or MINI_SIZE[0])
        return max(MINI_MIN, min(MINI_MAX, n))

    def _remember_pos(self):
        p = self._win.pos()
        self.state["pos_mini" if self.cur_mini else "pos_full"] = [p.x(), p.y()]

    def _place(self, w, h, pos):
        """Pindah ke pos (kalau masih di layar) lalu ganti ukuran."""
        if pos:
            pt = QPoint(int(pos[0]), int(pos[1]))
            scr = QGuiApplication.screenAt(pt + QPoint(w // 2, h // 2))
            if scr:
                g = scr.availableGeometry()
                pt.setX(max(g.left(), min(pt.x(), g.right() - w + 1)))
                pt.setY(max(g.top(), min(pt.y(), g.bottom() - h + 1)))
                self._win.move(pt)
        self._win.setFixedSize(w, h)

    def _apply_mode(self, mini):
        self._remember_pos()
        self.cur_mini = bool(mini)
        if mini:
            n = self.mini_size()
            self._place(n, n, self.state.get("pos_mini"))
        else:
            self._place(*FULL_SIZE, self.state.get("pos_full"))
        save_state(self.state)

    def _quit(self):
        self._remember_pos()
        save_state(self.state)
        QApplication.quit()

    @Slot(int)
    def miniWheel(self, direction):
        """Scroll di atas orb mini: perbesar/perkecil, pusat orb tetap di tempat."""
        if not self.cur_mini:
            return
        old = self._win.width()
        new = max(MINI_MIN, min(MINI_MAX, old + (MINI_STEP if direction > 0 else -MINI_STEP)))
        if new == old:
            return
        c = self._win.geometry().center()
        self._win.setFixedSize(new, new)
        self._win.move(c.x() - new // 2, c.y() - new // 2)
        self.state["mini_size"] = new
        self._remember_pos()
        save_state(self.state)

    @Slot(str, str, int)
    def call(self, name, args_json, call_id):
        """Panggilan JS -> Api. Seperti pywebview, tiap panggilan di thread sendiri agar UI tidak macet."""
        def work():
            result = None
            try:
                if name in API_METHODS:
                    result = getattr(self._api, name)(*json.loads(args_json or "[]"))
            except Exception:
                _log(f"[api {name}] " + traceback.format_exc())
            try:
                payload = json.dumps(result)
            except TypeError:
                payload = "null"
            self.runJs.emit(f"window.__qtResolve && window.__qtResolve({call_id}, {payload})")
        threading.Thread(target=work, daemon=True).start()

    @Slot()
    def startDrag(self):
        handle = self._win.windowHandle()
        if handle:
            handle.startSystemMove()

    @Slot(str)
    def setHitRects(self, rects_json):
        try:
            self._win.hit_rects = json.loads(rects_json)
        except Exception:
            pass

    def _run_js(self, code):
        try:
            self._win.page().runJavaScript(code)
        except Exception:
            pass

    def _on_top(self, on):
        """Selalu di atas lewat flag Qt di QWindow (bukan SetWindowPos langsung: Qt menimpanya lagi saat
        jendela tampil karena flag-nya sendiri bilang tidak topmost). QWindow.setFlag tidak menyembunyikan
        jendela seperti QWidget.setWindowFlags."""
        handle = self._win.windowHandle()
        if handle:
            handle.setFlag(Qt.WindowStaysOnTopHint, bool(on))
        if sys.platform == "win32":                       # cadangan bila flag Qt belum diterapkan
            flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            ctypes.windll.user32.SetWindowPos(int(self._win.winId()), HWND_TOPMOST if on else HWND_NOTOPMOST,
                                              0, 0, 0, 0, flags)


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        if level != QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel:
            _log(f"[js {level.name}] {source}:{line} {message}")


class HudWindow(QWebEngineView):
    """Jendela tanpa bingkai, latar transparan per piksel, klik tembus di luar HUD."""

    def __init__(self):
        super().__init__()
        self.hit_rects = []
        self._through = None
        self.setWindowTitle("Jarvis")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.setPage(Page(self))
        self.page().setBackgroundColor(QColor(0, 0, 0, 0))
        s = self.page().settings()
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.ShowScrollBars, False)
        self.setFixedSize(*FULL_SIZE)
        self._hover = QTimer(self)
        self._hover.timeout.connect(self._update_click_through)
        self._hover.start(40)

    def _update_click_through(self):
        """Klik tembus saat kursor di area transparan, normal saat di atas HUD."""
        if sys.platform != "win32" or not self.isVisible():
            return
        if QGuiApplication.mouseButtons() != Qt.NoButton:
            return                                   # jangan ganti di tengah klik/seret
        p = self.mapFromGlobal(QCursor.pos())
        inside_win = 0 <= p.x() < self.width() and 0 <= p.y() < self.height()
        on_hud = (not self.hit_rects) or any(x <= p.x() < x + w and y <= p.y() < y + h
                                             for x, y, w, h in self.hit_rects)
        through = inside_win and not on_hud
        if through == self._through:
            return
        self._through = through
        hwnd = int(self.winId())
        u = ctypes.windll.user32
        style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style = (style | WS_EX_TRANSPARENT | WS_EX_LAYERED) if through else (style & ~WS_EX_TRANSPARENT)
        u.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


class QtUI(WebUI):
    """Objek `ui` untuk jarvis.Jarvis; logika status dari WebUI, cara menggambar lewat Qt."""

    def __init__(self):
        super().__init__()
        self.bridge = None

    def js(self, code):
        with self.lock:
            if not self.ready:
                self.pending_js.append(code)
                return
        if self.bridge:
            self.bridge.runJs.emit(code)

    def on_loaded(self):
        with self.lock:
            self.ready = True
            todo, self.pending_js = self.pending_js, []
        for code in todo:
            self.bridge.runJs.emit(code)
        self.push()

    def on_top(self, on):
        if self.bridge:
            self.bridge.onTopReq.emit(bool(on))

    def set_mini(self, on):
        self.mini = bool(on)
        self.bridge.modeReq.emit(self.mini)
        self.js(f"window.jarvis && window.jarvis.setMini({json.dumps(self.mini)})")


class QtApi(Api):
    def onClose(self):
        app = self._app()
        if app:
            try:
                app.shutdown()
            except Exception:
                _log("[shutdown] " + traceback.format_exc())
        self._ui.bridge.quitReq.emit()


TESTED_PYSIDE = "6.8."


def run(core):
    import PySide6
    if not PySide6.__version__.startswith(TESTED_PYSIDE):
        _log(f"[versi] PySide6 {PySide6.__version__} belum diuji untuk kebocoran RAM; yang aman 6.8.3 "
             '(python -m pip install "PySide6==6.8.3")')
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QApplication.instance() or QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(True)

    ui = QtUI()
    api = QtApi(ui)
    settings = core.load_settings()

    win = HudWindow()
    bridge = Bridge(win, api)
    ui.bridge = bridge
    ui.window = win

    channel = QWebChannel(win.page())
    channel.registerObject("bridge", bridge)
    win.page().setWebChannel(channel)

    script = QWebEngineScript()
    script.setName("jarvis-qt-shim")
    script.setInjectionPoint(QWebEngineScript.DocumentReady)
    script.setWorldId(QWebEngineScript.MainWorld)
    script.setRunsOnSubFrames(False)
    script.setSourceCode(_qwebchannel_js() + "\n" + SHIM_JS % {"methods": json.dumps(API_METHODS)})
    win.page().scripts().insert(script)

    win.load(QUrl.fromLocalFile(INDEX))
    scr = qapp.primaryScreen().availableGeometry()
    win.move(scr.center() - QPoint(FULL_SIZE[0] // 2, FULL_SIZE[1] // 2))
    bridge._place(*FULL_SIZE, bridge.state.get("pos_full"))     # posisi terakhir mode penuh
    if settings.get("always_on_top"):
        win.setWindowFlag(Qt.WindowStaysOnTopHint, True)        # sebelum show: tidak perlu buat ulang jendela
    win.show()

    def start():
        try:
            core.Jarvis(ui)            # inti berjalan di thread sendiri; tampilan diperbarui lewat runJavaScript
        except Exception:
            _log("[core] " + traceback.format_exc())
            raise

    threading.Thread(target=start, daemon=True).start()
    code = qapp.exec()
    os._exit(code)                     # thread inti (audio, hotkey) daemon; pastikan proses benar-benar selesai
