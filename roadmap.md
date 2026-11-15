Roadmap Jarvis Suara untuk Claude Code
Aplikasi Windows bergaya terminal: kamu ngomong, Claude Code yang kerja, lalu jawabannya dibacakan dengan suara ElevenLabs.
Gambaran alur
1. Kamu ngomong ke mikrofon (tekan tombol untuk bicara).
2. Whisper lokal mengubah suara jadi teks bahasa Indonesia.
3. Teks dikirim ke Claude Code (pakai langganan Pro, tanpa API key Anthropic).
4. Claude Code mengerjakan tugas: jalankan perintah, edit file, cek proyek.
5. Ringkasan jawaban dikirim ke ElevenLabs (gratisan) lalu dibacakan.
Komponen
• Otak: Claude Code CLI, login dengan akun Pro.
• Telinga (STT): Whisper lokal, model kecil (base atau small) di CPU. GPU AMD RX 5600 XT kurang didukung, jadi jangan pakai model besar.
• Mulut (TTS): ElevenLabs paket gratis. Tetap butuh API key, tapi gratis dengan jatah karakter bulanan, jadi jawaban harus pendek.
• Wadah: aplikasi kecil Python yang tampil seperti PowerShell.
Tahap 1: Persiapan
• Pasang Claude Code di Windows, lalu login dengan akun Pro.
• Pasang Python 3.11 atau lebih baru.
• Daftar ElevenLabs gratis, ambil API key, pilih satu suara yang bisa bahasa Indonesia.
• Pastikan mikrofon USB jalan.
Tahap 2: Tes per bagian
• Tes Whisper: rekam 5 detik, cek hasil teks bahasa Indonesia.
• Tes Claude Code mode non-interaktif: kirim satu perintah dan ambil jawabannya sebagai teks.
• Tes ElevenLabs: kirim satu kalimat, dengarkan hasilnya.
Tahap 3: Gabungkan
• Satu skrip: tombol bicara, lalu Whisper, lalu Claude Code, lalu ElevenLabs.
• Minta Claude menjawab singkat 1 sampai 3 kalimat supaya jatah ElevenLabs hemat.
• Tampilkan log seperti terminal: yang kamu ucapkan, yang Claude kerjakan, dan jawabannya.
Tahap 4: Rapikan
• Bungkus jadi aplikasi Windows yang bisa dibuka sekali klik.
• Tambah konfirmasi suara sebelum perintah berisiko (hapus file, install).
• Simpan pengaturan: suara, folder kerja, tombol bicara.
Batasan yang perlu diingat
• Claude Code bekerja lewat terminal dan file, tidak bisa klik-klik layar di Windows.
• Pemakaian ikut kuota langganan Pro, jadi tugas berat bisa cepat kena limit.
• Jatah ElevenLabs gratis terbatas. Kalau habis, bisa pindah ke suara bawaan Windows.
Cara mulai
Buka Claude Code, lalu minta: buatkan aplikasi suara sesuai roadmap ini, mulai dari Tahap 2.