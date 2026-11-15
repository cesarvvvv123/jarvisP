"""Demo UI Jarvis tanpa mikrofon, tanpa Claude, tanpa kredit ElevenLabs.

Jalankan:  python ui_demo.py              (opsi: --mini mulai di mode mini, --settings buka Pengaturan)
Status berganti otomatis tiap 3 detik (siaga -> mendengarkan -> memproses -> berbicara -> kredit habis),
dengan level suara acak sekitar 30 kali per detik. Pengaturan bisa dibuka, tapi tidak disimpan.
"""
import random
import sys
import threading
import time

import webview

import jarvis
import ui_web

SAMPLES = {
    "idle": dict(transcript="", speech="", lines=[], meta=""),
    "listening": dict(transcript="tolong lihat isi folder ini", speech="", lines=[], meta=""),
    "processing": dict(transcript="tolong lihat isi folder ini", speech="", lines=[], meta=""),
    "speaking": dict(transcript="tolong lihat isi folder ini",
                     speech="Ada delapan folder dan banyak file, hasilnya di layar.",
                     lines=[{"t": "Folder: bantuan-ai-worker, ekstensi-dapodik, ikon-lms, lms-worker", "dot": "ok"},
                            {"t": "316 file: 47 HTML, 44 JS/MJS, 22 MD", "dot": "ok"},
                            {"t": "Folder aktif: E:\\AndroidStudioProjects\\lms_sekolah", "dot": "info"}],
                     meta="suara 54 karakter"),
    "warning": dict(transcript="buka kalkulator", speech="Sudah, kalkulatornya terbuka.",
                    lines=[{"t": "ElevenLabs 401: quota_exceeded", "dot": "warn"}],
                    meta="suara 29 karakter · cadangan", credit=6),
}
ORDER = ["idle", "listening", "processing", "speaking", "warning"]


class DemoApp:
    """Pengganti inti Jarvis untuk demo: pengaturan dibaca dari config, tidak pernah disimpan."""

    def __init__(self, ui):
        self.settings = jarvis.load_settings()
        self.ui = ui

    def apply_settings(self, new):
        print("demo: pengaturan TIDAK disimpan:", new)
        return None

    def start_rec(self):
        print("demo: tombol bicara ditekan")

    def stop_rec(self):
        print("demo: tombol bicara dilepas")

    def cancel(self):
        print("demo: batalkan")

    def set_wake(self, on):
        print("demo: panggil Jarvis =", on)

    def shutdown(self):
        pass


def cycle(ui):
    ui.app = DemoApp(ui)
    ui.data.update(project="lms sekolah", projectPath=r"E:\AndroidStudioProjects\lms_sekolah",
                   model=ui.app.settings.get("claude_model") or "haiku", credit=9450, time="3.5 dtk",
                   hotkey=ui.app.settings.get("hotkey", "F9"))
    while not ui.ready:
        time.sleep(0.1)
    if "--mini" in sys.argv:
        ui.set_mini(True)
    if "--settings" in sys.argv:
        ui.js("document.getElementById('bSet').click()")
    i = 0
    while True:
        name = ORDER[i % len(ORDER)]
        ui.data.update(dict({"credit": 9450}, **SAMPLES[name]))
        ui.state = "speaking" if name == "warning" else name
        ui.fallback = name == "warning"
        ui.push()
        end = time.time() + 3
        while time.time() < end:
            base = {"listening": 0.6, "speaking": 0.7, "warning": 0.6}.get(name, 0.3)
            ui.level(max(0.0, min(1.0, random.gauss(base, 0.2))))
            time.sleep(1 / 30)
        i += 1


def main():
    ui = ui_web.WebUI()
    api = ui_web.Api(ui)
    ui_web.make_window(ui, api)
    webview.start(lambda: threading.Thread(target=cycle, args=(ui,), daemon=True).start())


if __name__ == "__main__":
    main()
