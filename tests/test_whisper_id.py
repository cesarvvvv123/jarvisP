"""Bandingkan akurasi dan kecepatan Whisper: rekam 5 detik sekali, transkripsi dengan tiap model.

Pakai:
  python tests\\test_whisper_id.py                 # bandingkan base dan small
  python tests\\test_whisper_id.py small           # satu model saja
  python tests\\test_whisper_id.py base small --detik 8
Parameter transcribe sama persis dengan jarvis.py (diambil dari whisper_params).
"""
import argparse
import os
import sys
import time

import sounddevice as sd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jarvis import MIC_RATE, load_settings, whisper_params  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("models", nargs="*", default=["base", "small"])
ap.add_argument("--detik", type=int, default=5)
args = ap.parse_args()

settings = load_settings()
params = whisper_params(settings)
print(f"Bahasa: {params['language'] or 'auto'} | beam_size={params['beam_size']} | "
      f"prompt: {params['initial_prompt']}")

print(f"\nBicara sekarang selama {args.detik} detik (coba: 'Jarvis, open Chrome lalu buka folder')...")
audio = sd.rec(int(args.detik * MIC_RATE), samplerate=MIC_RATE, channels=1, dtype="float32")
sd.wait()
audio = audio.flatten()
print("Selesai merekam.\n")

for name in args.models:
    print(f"== model '{name}' ==")
    t0 = time.perf_counter()
    print("Memuat model... (pertama kali mengunduh, tunggu)")
    model = WhisperModel(name, device="cpu", compute_type="int8")
    t_load = time.perf_counter() - t0

    t0 = time.perf_counter()
    segments, info = model.transcribe(audio, **params)
    text = " ".join(s.text.strip() for s in segments).strip()
    t_run = time.perf_counter() - t0

    print(f"Hasil : {text or '(kosong)'}")
    print(f"Waktu : transkripsi {t_run:.2f} dtk | muat model {t_load:.2f} dtk | bahasa {info.language}\n")
