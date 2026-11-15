# jarvisP

Jarvis: asisten suara untuk Windows, berbahasa Indonesia. Kamu bicara, ucapanmu diubah jadi teks, lalu dikerjakan lewat Claude Code (buka aplikasi, kontrol browser, jalankan perintah), dan jawabannya dibacakan balik.

## Kebutuhan
- Windows 10/11
- Python 3.12
- Claude Code (CLI) terpasang dan sudah login
- Mikrofon

## Pasang
```
pip install numpy requests sounddevice
```
Tambahkan paket lain sesuai kebutuhan UI (misalnya PyQt) dan kunci API layanan suara (disimpan di variabel lingkungan Windows, bukan di file).

## Jalankan
```
jarvis.bat          # tanpa jendela konsol
jarvis.bat debug    # dengan konsol, untuk lihat error
```

## Struktur singkat
- `jarvis.py`: program utama
- `browser_guard.py`, `desktop.py`: penjaga keamanan dan kontrol desktop
- `hapus.py`: hapus file/folder ke Recycle Bin setelah diizinkan lewat suara
- `ui/`, `ui_*.py`: tampilan
- `settings.json`, `vocab.txt`, `corrections.txt`: pengaturan dan koreksi suara
- `ARSITEKTUR.md`: catatan arsitektur

## Hapus file atau folder
Bilang misalnya "Jarvis, hapus folder build di proyek lms". Claude cuma mencari path-nya (perintah hapus tetap diblokir), lalu Jarvis bertanya "Yakin hapus ...? Katakan ya atau tidak." Kalau "ya", Jarvis memindahkannya ke Recycle Bin, jadi masih bisa dikembalikan. Folder sistem (Windows, Program Files), akar drive, folder profil, dan folder Jarvis sendiri tidak bisa dihapus.

## Mikir dulu ("euuu")
Kalau ucapan berakhir dengan kata sambung (dan, atau, lalu, ...) Jarvis menunggu `connective_wait_ms`. Kalau berakhir dengan kata ragu seperti "euuu", "eee", "emm", "hmm", atau "anu", Jarvis menunggu lebih lama (`filler_wait_ms`, bawaan 3000 ms) dan kata ragunya dibuang sebelum perintah dikirim.

## Catatan
Proyek pribadi, masih berkembang. Jarvis tidak akan mengisi kata sandi atau data kartu.
