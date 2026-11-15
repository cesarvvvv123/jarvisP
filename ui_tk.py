"""UI lama Jarvis (Tkinter). Jalankan dengan:  python jarvis.py --legacy-ui

Tampilan sama seperti sebelum UI web: log teks, status, tombol tahan-bicara, centang "Panggil 'Jarvis'",
dialog Pengaturan. Semua logika ada di jarvis.Jarvis; kelas ini hanya tampilan.
"""
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText


class TkUI:
    def __init__(self, root, core):
        self.root, self.core = root, core       # core = modul jarvis (konstanta, user_env)
        self.app = None
        self.bound_key = None

    # ----- dipanggil oleh Jarvis -----
    def attach(self, app):
        self.app = app
        root = self.root
        root.title("Jarvis")
        root.geometry("820x540")
        root.configure(bg="#0c0c0c")

        self.log_box = ScrolledText(
            root, bg="#0c0c0c", fg="#cccccc", insertbackground="#cccccc",
            font=("Consolas", 11), wrap="word", borderwidth=0, state="disabled",
        )
        self.log_box.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        for tag, color in (("you", "#4fc3f7"), ("claude", "#a5d6a7"), ("sys", "#888888"),
                           ("err", "#ef5350"), ("say", "#ffd54f"), ("ask", "#ff9800"),
                           ("layar", "#ce93d8")):
            self.log_box.tag_config(tag, foreground=color)

        self.status_var = tk.StringVar(value="memuat...")
        bar = tk.Frame(root, bg="#0c0c0c")
        bar.pack(fill="x", padx=10)
        tk.Label(bar, textvariable=self.status_var, bg="#0c0c0c", fg="#888888",
                 font=("Consolas", 10), anchor="w").pack(side="left")
        self.folder_var = tk.StringVar(value=f"folder: {app.settings['work_dir']}")
        tk.Label(root, textvariable=self.folder_var, bg="#0c0c0c", fg="#4fc3f7",
                 font=("Consolas", 9), anchor="w").pack(fill="x", padx=10)
        tk.Button(bar, text="Pengaturan", command=self.open_settings, bg="#1f1f1f", fg="#cccccc",
                  relief="flat", font=("Consolas", 9)).pack(side="right")
        self.wake_var = tk.BooleanVar(value=bool(app.settings["wake_mode"]))
        tk.Checkbutton(bar, text="Panggil 'Jarvis'", variable=self.wake_var,
                       command=lambda: app.set_wake(self.wake_var.get()),
                       bg="#0c0c0c", fg="#cccccc", selectcolor="#1f1f1f", activebackground="#0c0c0c",
                       activeforeground="#ffffff", font=("Consolas", 9)).pack(side="right", padx=8)

        self.btn = tk.Button(
            root, font=("Consolas", 12, "bold"), bg="#1f1f1f", fg="#ffffff",
            activebackground="#2e7d32", relief="flat", pady=10,
        )
        self.btn.pack(fill="x", padx=8, pady=8)
        self.btn.bind("<ButtonPress-1>", lambda e: app.start_rec())
        self.btn.bind("<ButtonRelease-1>", lambda e: app.stop_rec())
        self.hotkey_changed(app.settings["hotkey"])
        self.on_top(bool(app.settings.get("always_on_top")))

    def log(self, text, tag="sys"):
        self.root.after(0, self._log, text, tag)

    def _log(self, text, tag):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n", tag)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def status(self, text):
        self.root.after(0, self.status_var.set, text)

    def folder(self, name, path):
        label = f"folder: {name} ({path})" if name != path else f"folder: {path}"
        self.root.after(0, self.folder_var.set, label)

    def wake_checked(self, on):
        self.root.after(0, self.wake_var.set, bool(on))

    def recording(self, on):
        self.root.after(0, lambda: self.btn.configure(bg="#2e7d32" if on else "#1f1f1f"))

    def level(self, value):
        pass                                    # UI lama tidak menampilkan level suara

    def credit(self, value):
        pass

    def model(self, wanted, actual):
        pass                                    # UI lama: model tampil lewat log

    def call_later(self, ms, fn):
        self.root.after(ms, fn)

    def on_top(self, on):
        self.root.after(0, lambda: self.root.attributes("-topmost", bool(on)))

    def hotkey_changed(self, key):
        def bind():
            if self.bound_key:
                self.root.unbind(f"<KeyPress-{self.bound_key}>")
                self.root.unbind(f"<KeyRelease-{self.bound_key}>")
            k = key
            try:
                self.root.bind(f"<KeyPress-{k}>", lambda e: self.app.start_rec())
                self.root.bind(f"<KeyRelease-{k}>", lambda e: self.app.stop_rec())
            except tk.TclError:
                k = "F9"
                self.app.settings["hotkey"] = k
                self.root.bind(f"<KeyPress-{k}>", lambda e: self.app.start_rec())
                self.root.bind(f"<KeyRelease-{k}>", lambda e: self.app.stop_rec())
            self.bound_key = k
            self.btn.configure(text=f"Tahan untuk bicara  ({k})")
        if threading.current_thread() is threading.main_thread():
            bind()
        else:
            self.root.after(0, bind)

    # ----- dialog Pengaturan (sama seperti UI lama) -----
    def open_settings(self):
        app, c = self.app, self.core
        win = tk.Toplevel(self.root)
        win.title("Pengaturan")
        win.resizable(False, False)
        win.transient(self.root)
        pad = {"padx": 8, "pady": 5}
        s = app.settings

        work = tk.StringVar(value=s["work_dir"])
        voice = tk.StringVar(value=s["voice_id"] or c.user_env("ELEVENLABS_VOICE_ID") or "")
        hotkey = tk.StringVar(value=s["hotkey"])
        model = tk.StringVar(value=s["whisper_model"])
        lang = tk.StringVar(value=s["whisper_language"])
        runmode = tk.StringVar(value=s["run_mode"])
        maxc = tk.StringVar(value=str(s["tts_max_chars"]))
        silence = tk.StringVar(value=str(s["end_silence_ms"]))
        merge = tk.StringVar(value=str(s["merge_window_ms"]))
        details = tk.BooleanVar(value=bool(s["speak_details"]))
        ack_on = tk.BooleanVar(value=bool(s.get("ack_enabled", True)))

        tk.Label(win, text="Folder kerja").grid(row=0, column=0, sticky="w", **pad)
        tk.Entry(win, textvariable=work, width=44).grid(row=0, column=1, **pad)
        tk.Button(win, text="...", command=lambda: work.set(
            filedialog.askdirectory(initialdir=work.get(), parent=win) or work.get()
        )).grid(row=0, column=2, **pad)

        tk.Label(win, text="Voice ID").grid(row=1, column=0, sticky="w", **pad)
        tk.Entry(win, textvariable=voice, width=44).grid(row=1, column=1, **pad)

        tk.Label(win, text="Tombol bicara").grid(row=2, column=0, sticky="w", **pad)
        tk.Entry(win, textvariable=hotkey, width=44, state="readonly").grid(row=2, column=1, **pad)

        def capture():
            hotkey.set("tekan tombol...")

            def on_key(e):
                hotkey.set(e.keysym)
                win.unbind("<KeyPress>")
            win.bind("<KeyPress>", on_key)
            win.focus_force()
        tk.Button(win, text="Ubah", command=capture).grid(row=2, column=2, **pad)

        tk.Label(win, text="Model Whisper").grid(row=3, column=0, sticky="w", **pad)
        tk.OptionMenu(win, model, "base", "small").grid(row=3, column=1, sticky="w", **pad)

        tk.Label(win, text="Bahasa Whisper").grid(row=4, column=0, sticky="w", **pad)
        tk.OptionMenu(win, lang, "id", "en", "auto").grid(row=4, column=1, sticky="w", **pad)

        tk.Label(win, text="Maks karakter suara").grid(row=5, column=0, sticky="w", **pad)
        tk.Entry(win, textvariable=maxc, width=10).grid(row=5, column=1, sticky="w", **pad)

        def save():
            err = app.apply_settings(dict(
                work_dir=work.get(), voice_id=voice.get(), hotkey=hotkey.get(), whisper_model=model.get(),
                whisper_language=lang.get(), tts_max_chars=maxc.get(), run_mode=runmode.get(),
                end_silence_ms=silence.get(), merge_window_ms=merge.get(), speak_details=details.get(),
                ack_enabled=ack_on.get(), projects=proj_box.get("1.0", "end"),
            ))
            if err:
                messagebox.showerror("Salah", err, parent=win)
                return
            win.destroy()

        tk.Label(win, text="Mode izin").grid(row=6, column=0, sticky="nw", **pad)
        modes = tk.Frame(win)
        modes.grid(row=6, column=1, sticky="w", **pad)
        tk.Radiobutton(modes, text="Langsung jalan (daftar blokir tetap berlaku)", variable=runmode,
                       value="direct").pack(anchor="w")
        tk.Radiobutton(modes, text="Minta izin (aman): tanya ya/tidak dulu", variable=runmode,
                       value="ask").pack(anchor="w")

        tk.Label(win, text="Batas diam (ms)").grid(row=7, column=0, sticky="w", **pad)
        sil_row = tk.Frame(win)
        sil_row.grid(row=7, column=1, sticky="w", **pad)
        tk.Entry(sil_row, textvariable=silence, width=10).pack(side="left")
        tk.Label(sil_row, text=f"{c.SILENCE_MIN_MS}-{c.SILENCE_MAX_MS}; diam selama ini = ucapan selesai",
                 fg="#666666").pack(side="left", padx=6)

        tk.Label(win, text="Gabung potongan (ms)").grid(row=8, column=0, sticky="w", **pad)
        mrg_row = tk.Frame(win)
        mrg_row.grid(row=8, column=1, sticky="w", **pad)
        tk.Entry(mrg_row, textvariable=merge, width=10).pack(side="left")
        tk.Label(mrg_row, text=f"0 = mati, maks {c.MERGE_MAX_MS}; tunda kirim agar potongan digabung",
                 fg="#666666").pack(side="left", padx=6)

        tk.Label(win, text="Rincian").grid(row=9, column=0, sticky="w", **pad)
        tk.Checkbutton(win, text="Bacakan rincian juga (bagian LAYAR; default mati)",
                       variable=details).grid(row=9, column=1, sticky="w", **pad)

        tk.Label(win, text="Proyek").grid(row=10, column=0, sticky="nw", **pad)
        proj_frame = tk.Frame(win)
        proj_frame.grid(row=10, column=1, columnspan=2, sticky="w", **pad)
        proj_box = tk.Text(proj_frame, width=58, height=4, font=("Consolas", 9))
        proj_box.pack(anchor="w")
        proj_box.insert("1.0", "\n".join(f"{n} = {p}" for n, p in (s.get("projects") or {}).items()))
        tk.Label(proj_frame, text="satu per baris: nama = path; ucapkan 'pindah ke <nama>'",
                 fg="#666666").pack(anchor="w")

        tk.Label(win, text="Sapaan").grid(row=11, column=0, sticky="w", **pad)
        tk.Checkbutton(win, text="Sapaan konfirmasi sebelum perintah aksi (\"Siap bos, saya kerjakan.\")",
                       variable=ack_on).grid(row=11, column=1, sticky="w", **pad)

        tk.Button(win, text="Simpan", command=save, width=14).grid(row=12, column=1, sticky="e", **pad)


def run(core):
    root = tk.Tk()
    ui = TkUI(root, core)
    app = core.Jarvis(ui)

    def on_close():
        app.shutdown()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
