"""Panel terminal interaktif di samping HUD Jarvis (PySide6).

Muncul lewat perintah suara "tampilkan terminal" / "buka terminalmu", bisa diketik, copy, paste, dan
diminimize ke bilah judul. Shell: PowerShell yang tetap hidup (subprocess), folder awal = folder proyek aktif.
parse_command() murni (tanpa Qt) supaya mudah dites.
"""
import os
import re
import subprocess
import sys
import threading

TERM_WORDS = {"terminal", "terminalnya", "terminalmu", "terminalku", "konsol", "console", "powershell"}
SHOW_VERBS = {"tampilkan", "tampilin", "tampilkn", "buka", "bukain", "bukakan", "munculkan", "munculin",
              "tunjukkan", "tunjukin", "show", "open", "nyalakan", "nyalain", "hidupkan"}
HIDE_VERBS = {"tutup", "tutupin", "tutupkan", "sembunyikan", "sembunyiin", "hide", "close", "matikan", "matiin"}
MIN_VERBS = {"minimize", "minimise", "kecilkan", "kecilin", "ciutkan"}
FILLERS = {"jarvis", "tolong", "dong", "deh", "ya", "yah", "aja", "saja", "donk", "sekarang", "coba", "bisa",
           "kamu", "kau", "di", "sampingku", "samping", "sebelah", "itu", "yang", "pak", "bro"}


def parse_command(text):
    """'show' / 'hide' / 'min' untuk perintah terminal yang pendek, selain itu None."""
    words = [w for w in re.sub(r"[^\w\s]", " ", (text or "").lower()).split() if w not in FILLERS]
    if not words or len(words) > 4 or not (set(words) & TERM_WORDS):
        return None
    ws = set(words)
    if ws & MIN_VERBS:
        return "min"
    if ws & HIDE_VERBS:
        return "hide"
    if ws & SHOW_VERBS:
        return "show"
    return None


try:
    from PySide6.QtCore import QPoint, Qt, Signal
    from PySide6.QtGui import QGuiApplication, QTextCursor
    from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout,
                                   QWidget)
except Exception:                       # PySide6 tidak ada: hanya parse_command yang dipakai
    QWidget = object
    Signal = lambda *a, **k: None       # supaya kelas di bawah tetap bisa didefinisikan (jarvis.py tetap jalan)

STYLE = """
#panel { background: rgba(6,16,30,238); border: 1px solid #1f8fff; border-radius: 8px; }
#title { color: #5fc8ff; font: bold 9pt "Consolas"; letter-spacing: 2px; }
QPushButton { background: transparent; color: #5fc8ff; border: none; font: bold 11pt "Consolas"; padding: 0 8px; }
QPushButton:hover { background: rgba(31,143,255,90); }
QPlainTextEdit { background: rgba(2,8,18,200); color: #bfe9ff; border: none; selection-background-color: #1f8fff;
                 font: 10pt "Consolas"; }
QLineEdit { background: rgba(2,8,18,230); color: #ffffff; border: 1px solid #1f8fff; border-radius: 4px;
            padding: 4px; font: 10pt "Consolas"; selection-background-color: #1f8fff; }
"""
BAR_H, FULL_W, FULL_H = 30, 560, 420


class TerminalPanel(QWidget):
    got = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Jarvis Terminal")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(STYLE)
        self.proc = None
        self.got.connect(self._append)
        self.cwd = os.path.expanduser("~")
        self.minimized = False
        self.history, self.hpos = [], 0
        self._drag = None

        frame = QWidget(self)
        frame.setObjectName("panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(8, 4, 8, 8)
        lay.setSpacing(4)

        bar = QHBoxLayout()
        self.title = QLabel("TERMINAL")
        self.title.setObjectName("title")
        self.btn_min = QPushButton("—")
        self.btn_close = QPushButton("×")
        self.btn_min.setToolTip("Minimize")
        self.btn_close.setToolTip("Tutup")
        self.btn_min.clicked.connect(lambda: self.toggle_min())
        self.btn_close.clicked.connect(self.hide)
        bar.addWidget(self.title, 1)
        bar.addWidget(self.btn_min)
        bar.addWidget(self.btn_close)
        lay.addLayout(bar)

        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setMaximumBlockCount(5000)
        self.out.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.inp = QLineEdit()
        self.inp.setPlaceholderText("ketik perintah, Enter jalankan (Ctrl+C tanpa teks terpilih = hentikan)")
        self.inp.returnPressed.connect(self.submit)
        self.inp.installEventFilter(self)
        self.body = [self.out, self.inp]
        lay.addWidget(self.out, 1)
        lay.addWidget(self.inp)
        self.resize(FULL_W, FULL_H)

    # ----- shell -----
    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start_shell(self):
        if self.alive():
            return
        cwd = self.cwd if os.path.isdir(self.cwd) else os.path.expanduser("~")
        flags = 0x08000000 if sys.platform == "win32" else 0          # CREATE_NO_WINDOW
        proc = subprocess.Popen(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "-"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                cwd=cwd, creationflags=flags)
        self.proc = proc
        threading.Thread(target=self._pump, args=(proc,), daemon=True).start()
        self._send("[Console]::OutputEncoding=[Text.Encoding]::UTF8; $ProgressPreference='SilentlyContinue'")

    def _pump(self, proc):
        """Thread pembaca: kirim keluaran shell ke thread utama lewat sinyal."""
        while True:
            try:
                data = os.read(proc.stdout.fileno(), 4096)
            except OSError:
                break
            if not data:
                break
            text = data.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "")
            self.got.emit(text)
        if proc is self.proc and not sys.is_finalizing():
            self.got.emit("\n[shell berhenti, Enter untuk mulai lagi]\n")

    def _send(self, line):
        try:
            self.proc.stdin.write((line + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except Exception:
            pass
        except Exception:
            pass

    def _append(self, text):
        bar = self.out.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4
        cur = self.out.textCursor()
        cur.movePosition(QTextCursor.End)
        cur.insertText(text)
        if at_end:
            bar.setValue(bar.maximum())

    def submit(self):
        cmd = self.inp.text()
        self.inp.clear()
        if not self.alive():
            self.start_shell()
        if cmd.strip():
            self.history.append(cmd)
        self.hpos = len(self.history)
        self._append(f"PS> {cmd}\n")
        if cmd.strip():
            self._send(cmd)

    def stop_running(self):
        """Ctrl+C tanpa teks terpilih: matikan shell, mulai baru."""
        old, self.proc = self.proc, None
        if old and old.poll() is None:
            old.kill()
        self._append("^C\n")
        self.start_shell()

    def eventFilter(self, obj, ev):
        if obj is self.inp and ev.type() == ev.Type.KeyPress:
            k = ev.key()
            if k == Qt.Key_Up and self.history:
                self.hpos = max(0, self.hpos - 1)
                self.inp.setText(self.history[self.hpos])
                return True
            if k == Qt.Key_Down and self.history:
                self.hpos = min(len(self.history), self.hpos + 1)
                self.inp.setText(self.history[self.hpos] if self.hpos < len(self.history) else "")
                return True
            if k == Qt.Key_C and ev.modifiers() & Qt.ControlModifier and not self.inp.hasSelectedText():
                self.stop_running()
                return True
        return super().eventFilter(obj, ev)

    # ----- tampilan -----
    def toggle_min(self, force=None):
        self.minimized = (not self.minimized) if force is None else bool(force)
        for w in self.body:
            w.setVisible(not self.minimized)
        self.btn_min.setText("▢" if self.minimized else "—")
        if self.minimized:
            self.setFixedHeight(BAR_H + 8)
        else:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.resize(self.width(), FULL_H)

    def show_beside(self, anchor, cwd=None):
        """Tampilkan di samping jendela `anchor` (HUD): kanan kalau muat, kalau tidak kiri."""
        if cwd and os.path.isdir(cwd):
            self.cwd = cwd
        self.start_shell()
        if self.minimized:
            self.toggle_min(False)
        if not self.isVisible():
            g = anchor.geometry()
            scr = QGuiApplication.screenAt(g.center()) or QGuiApplication.primaryScreen()
            a = scr.availableGeometry()
            x = g.right() + 6
            if x + FULL_W > a.right():
                x = g.left() - FULL_W - 6
            x = max(a.left(), min(x, a.right() - FULL_W))
            y = max(a.top(), min(g.top() + 40, a.bottom() - FULL_H))
            self.move(QPoint(x, y))
        self.show()
        self.raise_()
        self.activateWindow()
        self.inp.setFocus()

    def closeEvent(self, ev):
        if self.alive():
            self.proc.kill()
        super().closeEvent(ev)

    # seret lewat bilah judul
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and ev.position().y() <= BAR_H:
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev):
        if self._drag is not None:
            self.move(ev.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, ev):
        self._drag = None
