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
- `ui/`, `ui_*.py`: tampilan
- `settings.json`, `vocab.txt`, `corrections.txt`: pengaturan dan koreksi suara
- `ARSITEKTUR.md`: catatan arsitektur

## Catatan
Proyek pribadi, masih berkembang. Jarvis tidak akan mengisi kata sandi atau data kartu.
