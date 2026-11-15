"""Tes 3: kirim satu kalimat ke ElevenLabs, simpan mp3, putar.

Set dulu env var:
  setx ELEVENLABS_API_KEY "isi_key"
  setx ELEVENLABS_VOICE_ID "isi_voice_id"
lalu buka terminal baru.
"""
import os
import sys

import requests

api_key = os.environ.get("ELEVENLABS_API_KEY")
voice_id = os.environ.get("ELEVENLABS_VOICE_ID")
if not api_key or not voice_id:
    sys.exit("ELEVENLABS_API_KEY atau ELEVENLABS_VOICE_ID belum diset.")

resp = requests.post(
    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
    headers={"xi-api-key": api_key, "Content-Type": "application/json"},
    json={
        "text": "Halo, saya Jarvis. Tes suara berhasil.",
        "model_id": "eleven_multilingual_v2",
    },
    timeout=60,
)
if resp.status_code != 200:
    sys.exit(f"Gagal {resp.status_code}: {resp.text[:300]}")

out = os.path.join(os.path.dirname(__file__), "out.mp3")
with open(out, "wb") as f:
    f.write(resp.content)
print("Tersimpan:", out)
os.startfile(out)
