"""Tes 1: rekam 5 detik dari mic, ubah ke teks Indonesia pakai Whisper lokal (CPU)."""
import sounddevice as sd
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000
DURATION = 5
MODEL_SIZE = "base"  # ganti "small" kalau mau lebih akurat

print("Memuat model Whisper (pertama kali akan mengunduh)...")
model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")

print(f"Bicara sekarang selama {DURATION} detik...")
audio = sd.rec(int(DURATION * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="float32")
sd.wait()
print("Selesai merekam, memproses...")

segments, _ = model.transcribe(audio.flatten(), language="id")
text = " ".join(s.text.strip() for s in segments).strip()
print("Hasil:", text or "(kosong)")
