"""Kotak input untuk ElevenLabs API key + Voice ID. Disimpan ke env var user Windows (setx)."""
import subprocess
import tkinter as tk
from tkinter import messagebox


def save():
    key = key_entry.get().strip()
    voice = voice_entry.get().strip()
    if not key or not voice:
        messagebox.showerror("Kurang", "API key dan Voice ID wajib diisi.")
        return
    subprocess.run(["setx", "ELEVENLABS_API_KEY", key], check=True, capture_output=True)
    subprocess.run(["setx", "ELEVENLABS_VOICE_ID", voice], check=True, capture_output=True)
    messagebox.showinfo("Tersimpan", "Tersimpan. Buka terminal baru supaya env var terbaca.")
    root.destroy()


root = tk.Tk()
root.title("Jarvis - ElevenLabs")
root.resizable(False, False)
pad = {"padx": 10, "pady": 5}

tk.Label(root, text="API Key").grid(row=0, column=0, sticky="w", **pad)
key_entry = tk.Entry(root, width=48, show="*")
key_entry.grid(row=0, column=1, **pad)

tk.Label(root, text="Voice ID").grid(row=1, column=0, sticky="w", **pad)
voice_entry = tk.Entry(root, width=48)
voice_entry.grid(row=1, column=1, **pad)

tk.Button(root, text="Simpan", command=save, width=14).grid(row=2, column=1, sticky="e", **pad)
key_entry.focus()
root.mainloop()
