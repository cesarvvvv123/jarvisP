"""Tes 2: kirim satu perintah ke Claude Code non-interaktif, ambil jawaban sebagai teks."""
import subprocess

PROMPT = "Jawab singkat 1 kalimat dalam bahasa Indonesia: apa isi folder kerja ini?"

result = subprocess.run(
    ["claude", "-p", PROMPT, "--output-format", "text"],
    capture_output=True,
    text=True,
    encoding="utf-8",
    shell=True,
    timeout=180,
)
print("Exit code:", result.returncode)
print("Jawaban:", result.stdout.strip() or "(kosong)")
if result.stderr.strip():
    print("Stderr:", result.stderr.strip())
