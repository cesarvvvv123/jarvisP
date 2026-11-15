"""Bandingkan akurasi Whisper SEBELUM (prompt lama, beam 1, tanpa koreksi) dan SESUDAH (vocab.txt + proyek,
beam dari config, corrections.txt).

Rekaman uji: kalimat berisi kosakata khusus, dibuat sekali dengan Edge TTS (suara Indonesia, gratis) dan
disimpan di tests\\audio\\ supaya bisa dipakai ulang. Tambahkan rekaman suaramu sendiri sebagai
tests\\audio\\<nama>.wav dengan teks rujukan di tests\\audio\\<nama>.txt untuk ikut dinilai.

Pakai:  python tests\\test_whisper_akurasi.py
"""
import asyncio
import glob
import os
import re
import sys
import time

import numpy as np
import soundfile as sf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import jarvis  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402

AUDIO_DIR = os.path.join(ROOT, "tests", "audio")
OLD_PROMPT = ("Jarvis, Claude, Chrome, buka, tutup, close, jalankan, komputer, folder, aplikasi, "
              "kalkulator, Calculator")
SENTENCES = {
    "simantap": "Jarvis, buka proyek Simantap di Android Studio.",
    "flutter": "Tolong jalankan Flutter lalu cek Firebase.",
    "lms": "Pindah ke lms sekolah.",
    "sambo": "Kucing aku namanya Sambo.",
    "cingambul": "Sekolahnya di Cingambul, Majalengka.",
    "kalkulator": "Tutup kalkulator yang masih terbuka.",
    "jarvisp": "Buka folder jarvisP pakai Claude Code.",
    "konfirmasi": "Minta konfirmasi dulu sebelum hapus file.",
}


def make_clips():
    os.makedirs(AUDIO_DIR, exist_ok=True)
    import edge_tts
    for name, text in SENTENCES.items():
        mp3 = os.path.join(AUDIO_DIR, f"{name}.mp3")
        if not os.path.exists(mp3):
            asyncio.run(edge_tts.Communicate(text, "id-ID-ArdiNeural").save(mp3))
        with open(os.path.join(AUDIO_DIR, f"{name}.txt"), "w", encoding="utf-8") as f:
            f.write(text)


def load_16k(path):
    audio, rate = sf.read(path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != jarvis.MIC_RATE:
        n = int(len(audio) * jarvis.MIC_RATE / rate)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
    return audio


def words(s):
    return re.sub(r"[^\w\s]", " ", s.lower()).split()


def wer(ref, hyp):
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(1, len(r))


def run(model, audio, beam, prompt, correct):
    t0 = time.perf_counter()
    segs, _ = model.transcribe(audio, language="id", beam_size=beam, vad_filter=True,
                               condition_on_previous_text=False, initial_prompt=prompt)
    text = " ".join(s.text.strip() for s in segs).strip()
    dt = time.perf_counter() - t0
    fixes = []
    if correct:
        text, fixes = jarvis.apply_corrections(text)
    return text, dt, fixes


def main():
    make_clips()
    settings = jarvis.load_settings()
    beam = int(settings.get("whisper_beam", 3))
    new_prompt = jarvis.build_whisper_prompt(settings)
    print(f"Model: {settings['whisper_model']} | prompt baru: {new_prompt}\n")
    model = WhisperModel(settings["whisper_model"], device="cpu", compute_type="int8")
    run(model, np.zeros(jarvis.MIC_RATE, dtype=np.float32), 1, OLD_PROMPT, False)        # pemanasan

    clips = []
    for path in sorted(glob.glob(os.path.join(AUDIO_DIR, "*.mp3")) + glob.glob(os.path.join(AUDIO_DIR, "*.wav"))):
        ref_path = os.path.splitext(path)[0] + ".txt"
        if os.path.exists(ref_path):
            clips.append((os.path.basename(path), load_16k(path), open(ref_path, encoding="utf-8").read().strip()))

    tot = {"before": [0.0, 0.0], "after": [0.0, 0.0]}
    for name, audio, ref in clips:
        b_text, b_dt, _ = run(model, audio, 1, OLD_PROMPT, False)
        a_text, a_dt, fixes = run(model, audio, beam, new_prompt, True)
        b_wer, a_wer = wer(ref, b_text), wer(ref, a_text)
        tot["before"][0] += b_wer; tot["before"][1] += b_dt
        tot["after"][0] += a_wer; tot["after"][1] += a_dt
        print(f"[{name}] rujukan : {ref}")
        print(f"  sebelum (beam 1) {b_dt:5.2f} dtk  WER {b_wer:4.0%} : {b_text}")
        print(f"  sesudah (beam {beam}) {a_dt:5.2f} dtk  WER {a_wer:4.0%} : {a_text}"
              + (f"   koreksi: {fixes}" if fixes else ""))
    n = max(1, len(clips))
    print(f"\nRATA-RATA {len(clips)} klip:")
    for k, label in (("before", "sebelum"), ("after", "sesudah")):
        print(f"  {label}: WER {tot[k][0] / n:4.0%} | waktu transkripsi {tot[k][1] / n:.2f} dtk per klip")


if __name__ == "__main__":
    main()
