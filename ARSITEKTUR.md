# Audit Arsitektur Jarvis

Tanggal audit: 2026-11-12. Semua bukti diambil dari kode di folder ini (`jarvis.py`, `ui_web.py`, `ui/index.html`, `ui_tk.py`, `settings.json`, `tests/`), dari output `claude --help`, `claude mcp --help`, dan `claude auth status` versi terpasang, serta dari dokumentasi resmi di code.claude.com. Selama audit tidak ada file yang diubah, kecuali dokumen ini.

Versi Claude Code terpasang: **2.1.322 (Claude Code)**, dipasang lewat npm di `%APPDATA%\npm\` (`claude.cmd`, dan biner aslinya di `node_modules\@anthropic-ai\claude-code\bin\claude.exe`).

---

## 1. Cara Python menjalankan Claude Code

**Jawaban:** Python menjalankan Claude Code sebagai **subprocess CLI** (`claude.exe -p`). Jarvis tidak memakai Agent SDK. Pencarian `claude_agent_sdk` dan `anthropic` di semua file `.py` hanya menemukan path biner di `jarvis.py:412`.

Prosesnya **dibiarkan tetap hidup** (persistent). Setiap perintah dikirim sebagai satu baris JSON lewat stdin (`--input-format stream-json`). Dengan cara ini Jarvis tidak membuat proses baru untuk tiap perintah.

### Bukti

| Bagian | Lokasi |
|---|---|
| Path biner: `.cmd` npm diganti `claude.exe`, karena cmd.exe memotong argumen yang berisi baris baru | `jarvis.py:407-415` |
| `subprocess.Popen` dengan stdin, stdout, dan stderr berupa PIPE, `cwd=work_dir`, `CREATE_NO_WINDOW` | `jarvis.py:499-502` (kelas `ClaudeSession`, `jarvis.py:491-542`) |
| Penyusunan perintah | `Jarvis.claude_cmd`, `jarvis.py:1417-1441` |
| Env: salinan `os.environ` ditambah `MAX_THINKING_TOKENS=0` | `jarvis.py:1457` |
| Batas panjang command line 7000 karakter | `jarvis.py:1455-1456` |
| Pemanasan: proses dinyalakan setelah Whisper siap | `jarvis.py:902-909` |
| Tes lama (tidak dipakai aplikasi): `claude -p PROMPT --output-format text`, `shell=True` | `tests/test_claude.py:6-13` |

### Perintah lengkap (dengan `settings.json` saat ini)

```
claude.exe -p
  --input-format stream-json --output-format stream-json
  --verbose --include-partial-messages
  --permission-mode bypassPermissions          # run_mode=direct; kalau "ask" -> acceptEdits
  --permission-prompts none                    # apa pun yang butuh izin langsung ditolak
  --system-prompt "<SYSTEM_PROMPT, jarvis.py:35-55>"
  --strict-mcp-config --disable-slash-commands # tanpa MCP, tanpa skill/slash command
  --setting-sources project,local              # settings tingkat user (~/.claude/settings.json) dilewati
  --model sonnet                               # settings.json:77
  --effort low                                 # settings.json:78
  --tools Bash,PowerShell,Read,Write,Edit,Glob,Grep   # settings.json:83
  --session-id <uuid4>   ATAU   --resume <uuid4>
  --add-dir E:\AndroidStudioProjects\lms_sekolah      # proyek lain dari "projects"
  [--allowedTools Bash(<cmd>) ...]                    # hanya setelah pengguna bilang "ya"
  --disallowedTools Bash(rm) "Bash(rm *)" PowerShell(rm) "PowerShell(rm *)" ...  # dari deny_list, selalu di akhir
cwd = work_dir (settings.json:2), env = os.environ + MAX_THINKING_TOKENS=0
```

Sumber tiap flag ada di `jarvis.py:1420-1440`. Aturan deny dibangun oleh `build_deny_rules`, `jarvis.py:331-338`. `--disallowedTools` sengaja ditaruh paling akhir karena argumennya variadic (`jarvis.py:1440`).

### Kapan proses dinyalakan ulang

`get_session` (`jarvis.py:1443-1459`) membandingkan kunci `(run_mode, deny_list, claude_model, claude_effort, claude_tools, work_dir, project_dirs, allow)`. Kalau kunci berubah atau proses mati, proses lama di-kill lalu proses baru dibuat dengan `--resume`.

---

## 2. Autentikasi Claude

**Jawaban:** Kode Jarvis **tidak menangani autentikasi Claude sama sekali**. Tidak ada API key Anthropic di kode atau di `settings.json`. CLI memakai kredensial yang sudah tersimpan di mesin.

Hasil `claude auth status` (dijalankan saat audit):

```
"loggedIn": true, "authMethod": "claude.ai", "apiProvider": "firstParty",
"subscriptionType": "pro", "loginExpiresAt": "2026-12-10T14:58:46.052Z"
```

Kredensial OAuth tersimpan di `%USERPROFILE%\.claude\.credentials.json`. Artinya tagihan masuk ke **langganan Pro**, bukan per token.

### Cek ANTHROPIC_API_KEY dan kredensial lain yang bisa menimpa

Hanya keberadaan variabel yang diperiksa, isinya tidak dibaca.

| Variabel | Proses | User (registry) | Machine |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | tidak ada | tidak ada | tidak ada |
| `ANTHROPIC_AUTH_TOKEN` | tidak ada | tidak ada | tidak ada |
| `CLAUDE_CODE_OAUTH_TOKEN` | tidak ada | tidak ada | tidak ada |
| `ANTHROPIC_BASE_URL` | tidak ada | tidak ada | tidak ada |
| `CLAUDE_CODE_USE_BEDROCK` / `_VERTEX` | tidak ada | (tidak dicek) | (tidak dicek) |

Folder `.claude/` tidak ada di `jarvisP` maupun `lms_sekolah`. Jadi tidak ada `env` atau `apiKeyHelper` dari sumber `project`/`local`. Settings tingkat user tidak dimuat karena `--setting-sources project,local` (`jarvis.py:1426`).

### Risiko: API key bisa menimpa langganan

- `jarvis.py:1457` meneruskan **seluruh** `os.environ` ke proses Claude. Kode tidak membuang `ANTHROPIC_API_KEY` atau `ANTHROPIC_AUTH_TOKEN`.
- Menurut dokumentasi resmi (code.claude.com/docs/en/iam, "Authentication precedence"), urutannya: cloud provider > `ANTHROPIC_AUTH_TOKEN` > `ANTHROPIC_API_KEY` > `apiKeyHelper` > `CLAUDE_CODE_OAUTH_TOKEN` > login `/login`. Dokumentasi juga menulis: *"In non-interactive mode (`-p`), the key is always used when present."*
- Akibatnya: kalau suatu saat `ANTHROPIC_API_KEY` di-set, misalnya lewat `setx` seperti `set_keys.py` menyimpan kunci ElevenLabs, Jarvis yang dijalankan sesudahnya akan **langsung ditagih per token tanpa ditanya**. Saat ini variabel itu tidak ada, jadi risikonya belum terjadi.
- Catatan: `user_env()` (`jarvis.py:287-297`) membaca registry hanya untuk kunci ElevenLabs dan Groq, bukan untuk Claude.
- Rekomendasi (belum diterapkan): buang `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, dan `ANTHROPIC_BASE_URL` dari `env` di `jarvis.py:1457`. Bisa juga tambahkan pengecekan `apiKeySource` dari event `system/init`.
- `modelUsage.costUSD` dibaca di `jarvis.py:1657` hanya untuk menentukan model asli. Pada langganan, angka itu perkiraan, bukan tagihan.

---

## 3. Sesi, percakapan, timeout, dan pembatalan

### Sesi dan konteks

- Saat Jarvis start, dibuat satu `session_id = uuid4()` (`jarvis.py:567`), dengan `session_started = False` (`jarvis.py:568`).
- Proses pertama memakai `--session-id <uuid>`. Setelah satu giliran sukses (event `result` tanpa error), `session_started = True` (`jarvis.py:1649`). Proses yang dinyalakan ulang sesudahnya memakai `--resume <uuid>` (`jarvis.py:1434`).
- **Konteks percakapan terbawa antar perintah.** Selama proses hidup, semua perintah masuk ke proses yang sama lewat stdin (`ClaudeSession.send`, `jarvis.py:519-533`). Kalau proses dinyalakan ulang, misalnya karena ganti model, Esc, atau timeout, konteks dilanjutkan lewat `--resume`.
- Sebelum giliran baru, event sisa di antrean dibuang (`jarvis.py:520-527`).
- `--continue` tidak dipakai. `--no-session-persistence` juga tidak dipakai, jadi transkrip tersimpan di `~/.claude/projects`.
- **Percakapan baru** dibuat saat folder kerja utama berganti (`new_conversation`, `jarvis.py:1477-1482`). Ini dipanggil dari `switch_project` (`jarvis.py:1510`) dan `apply_settings` (`jarvis.py:702-703`).
- `session_id` **tidak disimpan ke disk**. Kalau Jarvis ditutup lalu dibuka lagi, percakapan mulai dari awal.
- Dari `claude --help`: `--system-prompt-snapshot` bawaannya `on`. Artinya system prompt direkam pada request pertama dan dipakai ulang saat `--resume`. Perubahan `SYSTEM_PROMPT` baru berlaku di percakapan baru. Kode tidak mengatur flag ini.
- **Tidak jelas:** perilaku saat giliran pertama dibatalkan atau timeout sebelum ada `result`. `session_started` masih `False`, jadi proses baru memakai `--session-id` dengan UUID yang sama. Dari kode tidak bisa dipastikan apakah CLI menerimanya atau menolak karena ID sudah dipakai.

### Timeout

- `CLAUDE_TIMEOUT = 300` detik (`jarvis.py:31`). Batas waktu dihitung dari saat perintah dikirim (`jarvis.py:1534`), bukan dari event terakhir.
- Batas itu hanya dicek saat antrean kosong selama 1 detik (`jarvis.py:1582-1588`). Selama event terus mengalir, giliran bisa melewati 300 detik.
- Saat timeout: `close_session()` (proses di-kill), lalu log "Claude kelamaan" (`jarvis.py:1633-1637`).
- Timeout lain: Groq 10 detik (`jarvis.py:228`), ElevenLabs 60 detik (`jarvis.py:1707`), dan suara lokal sapaan 30 detik (`jarvis.py:871`).

### Pembatalan (Esc)

1. UI web: `keydown` Escape memanggil `onCancel` (`ui/index.html:482`). Menekan tombol bicara saat status `processing` juga memanggil `onCancel` (`ui/index.html:443`).
2. `ui_web.py:216-218` meneruskannya ke `Jarvis.cancel()`.
3. `Jarvis.cancel` (`jarvis.py:772-784`) melakukan tiga hal. Potongan ucapan yang tertahan dibuang. Suara yang sedang diputar dihentikan (`SpeechSession.interrupt` lalu `sd.stop()`, `jarvis.py:1782-1786`). Kalau Claude sedang bekerja, `cancelled = True` dan `close_session()` membunuh proses (`proc.kill()`, `jarvis.py:538-542`).
4. Thread pembaca stdout mengirim `None` ke antrean (`jarvis.py:513-514`). Loop di `ask_claude` keluar, lalu log "Dibatalkan" (`jarvis.py:1628-1632`).

Dua catatan lain:

- UI Tk lama (`ui_tk.py`) tidak punya binding Esc. Pencarian `Escape`/`Esc` di file itu tidak menemukan apa pun.
- **Tidak jelas:** apakah `proc.kill()` di Windows ikut menghentikan proses anak (bash/PowerShell yang dijalankan alat Claude). Kode hanya membunuh `claude.exe`, bukan pohon prosesnya.

---

## 4. Pengiriman prompt dan penerimaan output

### Masuk (prompt)

- **System prompt:** memakai `--system-prompt` (menggantikan prompt bawaan CLI, bukan `--append-system-prompt`). Isinya `SYSTEM_PROMPT` di `jarvis.py:35-55`, disisipkan di `jarvis.py:1424`.
- **Prompt pengguna:** dikirim lewat **stdin** sebagai JSON per baris: `{"type":"user","message":{"role":"user","content":[{"type":"text","text":...}]}}` (`jarvis.py:528-531`). Prompt tidak dikirim sebagai argumen.
- Setiap perintah ditambah `FORMAT_REMINDER` (`jarvis.py:58-62`, ditempel di `jarvis.py:1531`). Isinya pengingat agar format UCAPAN/LAYAR dipatuhi.
- Sebelum dikirim, teks melewati beberapa tahap: koreksi `corrections.txt` (`jarvis.py:201-209`, `jarvis.py:1143`), filter kata panggil (`jarvis.py:1057-1093`), dan cek keyakinan (`jarvis.py:1292-1302`). Potongan ucapan bisa digabung dulu (`jarvis.py:1219-1257`).
- Ada perintah yang ditangani lokal **tanpa Claude**: ganti/tanya model (`jarvis.py:1282-1285`) dan "pindah ke <proyek>" (`jarvis.py:1286-1289`).

### Keluar (output)

- Format output **streaming JSON** (`--output-format stream-json --verbose --include-partial-messages`).
- Event dibaca thread `_read_out` (`jarvis.py:506-514`) lalu diproses di `ask_claude` (`jarvis.py:1581-1622`):
  - `stream_event`: `message_start` (reset), `content_block_start` bertipe `tool_use` (tandai ada alat), `content_block_delta`/`text_delta` (teks ditambahkan ke buffer), `message_stop` (finalisasi).
  - `assistant`: mencatat alat yang dipanggil (`jarvis.py:1609-1612`). Ini juga jalur cadangan kalau event parsial tidak ada (`jarvis.py:1615-1618`).
  - `result`: jawaban akhir, `permission_denials`, `modelUsage`, `is_error` (`jarvis.py:1620-1622`, `jarvis.py:1644-1651`).

### Pemisahan UCAPAN dan LAYAR

- System prompt mewajibkan dua label: `UCAPAN:` (maksimal 12 kata) dan `LAYAR:` (rincian, atau `-`) (`jarvis.py:46-54`).
- Regex: `UCAP_RE` dan `LAYAR_RE` (`jarvis.py:363-364`). Keduanya toleran terhadap tanda `**` dan huruf kecil.
- **Streaming awal:** `stream_ucapan` (`jarvis.py:1546-1559`) langsung membacakan UCAPAN begitu barisnya selesai (ada label LAYAR atau baris baru). Jarvis tidak menunggu LAYAR selesai ditulis.
- **Finalisasi:** `parse_reply` (`jarvis.py:372-393`). Kalau label tidak ada, kalimat pertama jadi ucapan dan sisanya jadi layar. `LAYAR: -` dianggap kosong.
- Teks yang ditulis sebelum alat dipanggil hanya ditampilkan, tidak dibacakan (`jarvis.py:1569-1573`).
- Ada batas keras suara per giliran: `speech_cap_chars` = 120 (`settings.json:8`, `fit_speech` di `jarvis.py:396-404`, `SpeechSession.say_answer` di `jarvis.py:1742-1751`). Bagian LAYAR hanya dibacakan kalau `speak_details` aktif. Saat ini nilainya `false` (`settings.json:9`).
- Kalau tidak ada pesan yang sempat diproses lewat stream, hasil akhir di `result` yang dipakai (`jarvis.py:1376-1383`).

### Izin dan blokir (bagian dari output `result`)

- Mode `direct`: setiap `permission_denials` dianggap kena daftar blokir. Jarvis mengucapkan "Itu diblokir." (`jarvis.py:1343-1352`).
- Mode `ask`: perintah yang ditolak ditanyakan ya/tidak lewat suara (`jarvis.py:1355-1374`). Kalau dijawab "ya", sesi dinyalakan ulang dengan `--allowedTools` (`jarvis.py:1269-1272`, `jarvis.py:1438-1439`).

---

## 5. Alur suara: mikrofon sampai suara keluar

```
Mikrofon (sounddevice 16 kHz mono)
 ├─ Mode panggil: listen_loop, VAD energi RMS             jarvis.py:981-1048
 │    blok 30 ms, ambang adaptif, preroll 0,3 dtk, akhir = diam end_silence_ms (1500, settings.json:85)
 └─ Tahan tombol (F9 / tombol UI): start_rec / stop_rec    jarvis.py:912-957
        ↓ jobs queue → worker → process                      jarvis.py:1096-1167
Transkripsi: transcribe()                                    jarvis.py:1108-1124
 ├─ stt_engine = "groq" (settings.json:14): Groq whisper-large-v3-turbo, WAV PCM16,
 │    verbose_json, temperature 0, prompt kosakata, timeout 10 dtk   jarvis.py:224-253
 │    kunci GROQ_API_KEY dari env atau registry user (user_env)
 └─ FALLBACK otomatis kalau Groq gagal: faster-whisper lokal "small", CPU int8,
      beam 3, vad_filter, initial_prompt kosakata               jarvis.py:886-902, 212-221
      model dimuat sekali dan dipanaskan dengan 1 dtk audio kosong (jarvis.py:894)
        ↓
corrections.txt → filter kata panggil "jarvis" → cek keyakinan (logprob/no_speech)
 → gabung potongan → dispatch                               jarvis.py:1143-1290
        ↓
(Opsional) sapaan "Siap bos…" dari cache, diputar paralel dengan kerja Claude
 → ack_enabled saat ini FALSE (settings.json:10)            jarvis.py:1326-1329
        ↓
Claude (bagian 1-4) → UCAPAN
        ↓
SpeechSession: 2 thread, fetch dan play berjalan paralel   jarvis.py:1726-1853
 ├─ fetch_tts: ElevenLabs /v1/text-to-speech/{voice}, output pcm_24000,
 │    model eleven_v4_turbo (settings.json:84), timeout 60   jarvis.py:1664-1718
 │    sisa kredit dikurangi lokal; kalau error, angka kredit diambil dari teks error
 └─ FALLBACK (fallback_voice = true): Edge TTS id-ID-ArdiNeural (gratis, butuh internet)
                                                             jarvis.py:1672-1695
        ↓
sounddevice.play; level suara dikirim ke UI; mic "muted" selama Jarvis bicara + 0,5 dtk
                                                             jarvis.py:1806-1853, 1004-1015
```

### Caching

- **Hanya sapaan konfirmasi yang di-cache.** File mp3 ElevenLabs disimpan di `cache/ack/<md5(voice|model|frasa)>.mp3` (`jarvis.py:815-845`). Saat ini ada 3 file mp3 di folder itu.
- Kalau ElevenLabs gagal, sapaan dibuat dengan suara lokal Windows `System.Speech` (`lokal_*.wav`, `jarvis.py:866-875`).
- **Jawaban Claude tidak di-cache.** Setiap kalimat jawaban memakai kredit ElevenLabs.
- Kosakata Whisper (`vocab.txt`) dan `corrections.txt` di-cache di memori. Keduanya dibaca ulang kalau `mtime` file berubah (`jarvis.py:153-165`).
- Model Whisper lokal dimuat sekali lalu dipakai ulang (`jarvis.py:895`).

### Temuan

- `SpeechSession.ok` bernilai `True` hanya kalau kunci **dan** voice ElevenLabs ada (`jarvis.py:1732`). Kalau `ok` bernilai `False`, `say` dan `say_answer` langsung berhenti (`jarvis.py:1747`, `jarvis.py:1757`). Akibatnya: **kalau kunci ElevenLabs tidak di-set, Edge TTS juga tidak pernah dipakai.** Fallback Edge hanya berjalan saat kunci ada tapi request gagal, misalnya karena kredit habis atau jaringan putus. Saat ini `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, dan `GROQ_API_KEY` sudah di-set di env User.
- `SENT_END` (`jarvis.py:264`) disebut "batas kalimat untuk suara streaming". Dalam praktiknya regex itu hanya dipakai `parse_reply` saat label tidak ada. Pembacaan suara dilakukan per baris UCAPAN, bukan per kalimat.

---

## 6. Computer Use dan ekstensi Chrome

### Yang ada di CLI terpasang (2.1.322)

Dari `claude --help`:

- `--chrome` (*"Enable Claude in Chrome integration"*) dan `--no-chrome`.
- `--mcp-config <configs...>` (*"Load MCP servers from JSON files or strings"*) dan `--strict-mcp-config` (*"Only use MCP servers from --mcp-config"*).
- Flag khusus Computer Use tidak ada.

Dari `claude mcp --help`: tersedia `add`, `add-json`, `list`, `get`, `remove`, `serve`, dan lainnya. Transport yang didukung: stdio, sse, http.

### Uji langsung `--chrome` di mode `-p`

Uji ini dilakukan saat audit dengan prompt kecil, model haiku, `--tools ""`, dan `--no-session-persistence`:

| Varian | Hasil event `system/init` |
|---|---|
| `-p --chrome` | server `claude-in-chrome` **connected**, tool `mcp__claude-in-chrome__*` tersedia |
| `-p --chrome --strict-mcp-config` (setara Jarvis) | **hanya** `claude-in-chrome` yang connected, tool browser tersedia |

Kesimpulan:

- **`--chrome` bekerja di mode `-p`** dan **tidak diblokir oleh `--strict-mcp-config`**.
- `--tools ""` tidak menghapus tool MCP. Artinya `--tools` hanya membatasi alat bawaan.

### Syarat Chrome (docs: code.claude.com/docs/en/chrome)

- Ekstensi Claude in Chrome versi 1.0.36 atau lebih baru.
- Plan Anthropic langsung (Pro memenuhi syarat).
- Login lewat `/login` (claude.ai). Dokumentasi menulis: *"If you authenticate with an API key or a long-lived token … Claude Code keeps Chrome integration off, even when you pass `--chrome`."* Ini alasan lain untuk tidak pernah membiarkan `ANTHROPIC_API_KEY` masuk ke env Jarvis (bagian 2).
- Ekstensi harus login ke organisasi yang sama dengan CLI.
- Izin per situs mengikuti pengaturan di ekstensi. **Tidak jelas:** bagaimana izin situs yang belum disetujui diperlakukan saat `--permission-prompts none` dan `bypassPermissions`. Dokumentasi tidak menjelaskan kombinasi ini untuk `-p`, jadi perlu diuji.

### Computer Use (docs: code.claude.com/docs/en/computer-use)

- Dokumentasi menulis: *"Computer use is a research preview on macOS … It requires an interactive session, so it is not available in non-interactive mode with the `-p` flag."*
- Di CLI, Computer Use **hanya tersedia di macOS**. Untuk Windows, dokumentasi mengarahkan ke Computer Use di aplikasi Claude Desktop.
- **Kesimpulan: Computer Use resmi tidak bisa dipakai Jarvis**, karena Jarvis berjalan di Windows dan memakai `-p`.
- Server MCP pihak ketiga untuk kontrol desktop Windows secara teknis bisa disambungkan lewat `--mcp-config`. Server seperti itu bukan produk resmi Anthropic dan tidak diuji di audit ini.

### Playwright MCP lewat `--mcp-config`

- Secara teknis bisa. `--mcp-config` diterima di mode `-p`, dan `--strict-mcp-config` justru membuat **hanya** server dari `--mcp-config` yang dimuat. Contoh: `--mcp-config "{\"mcpServers\":{\"playwright\":{\"command\":\"npx\",\"args\":[\"@playwright/mcp@<versi>\"]}}}"`.
- Server ini tidak diuji di audit ini (butuh unduhan npx).

### Rekomendasi

Pilih **`--chrome` (resmi, sudah terbukti jalan di `-p`)** untuk tugas di situs yang butuh login. Pilih **Playwright MCP dengan profil browser terpisah** untuk otomasi umum yang tidak butuh akun pribadi.

Cara memasangnya (belum diterapkan):

1. Tambahkan opsi `browser` di `settings.json`, dengan nilai `off`, `chrome`, atau `playwright`. Di `claude_cmd`, tambahkan `--chrome` atau `--mcp-config …` sesuai pilihan. Masukkan opsi ini ke kunci `get_session` agar sesi dinyalakan ulang saat berubah.
2. Jangan pakai `bypassPermissions` bersamaan dengan alat browser. Pakai `acceptEdits` dan izinkan alat browser secara spesifik lewat `--allowedTools "mcp__claude-in-chrome__*"`, atau nama tool Playwright. `deny_list` Jarvis (`jarvis.py:89-96`) hanya mencakup Bash dan PowerShell, bukan alat browser.
3. Untuk Chrome, pakai profil Chrome khusus yang hanya login ke situs yang memang perlu. Batasi situs di pengaturan ekstensi.

Risiko:

| Aspek | Risiko |
|---|---|
| **Keamanan** | Chrome memakai sesi login asli (email, bank, admin). Konten halaman web bisa berisi *prompt injection*, dan Jarvis juga punya Bash/PowerShell dengan `bypassPermissions`. Kombinasi ini paling berbahaya. Perintah suara juga bisa salah tangkap, padahal aksi web (kirim, beli, hapus) sering tidak bisa dibatalkan. |
| **Izin** | `--permission-prompts none` berarti tidak ada yang bisa menyetujui di tengah jalan. Alur ya/tidak lewat suara di Jarvis hanya membaca `tool_input.command` (`jarvis.py:1357-1366`). Jadi penolakan alat browser **tidak** akan ditanyakan ke pengguna, hanya dianggap diblokir di mode `direct`. Izin per situs ekstensi di mode `-p`: tidak jelas. |
| **Kecepatan** | Aksi browser dan screenshot lambat dan memakan token konteks. Ini bisa menabrak `CLAUDE_TIMEOUT` 300 dtk (`jarvis.py:31`). Dokumentasi juga menyebut alat browser menambah pemakaian konteks. Playwright via `npx` menambah waktu start setiap kali sesi dinyalakan ulang (ganti model, Esc, timeout). |
| **Batas langganan** | Tugas browser yang panjang menghabiskan kuota Pro lebih cepat. |
| **Pembatalan** | Esc membunuh `claude.exe` (`jarvis.py:538-542`). Menurut dokumentasi Chrome, saat sesi berakhir grup tab hanya ditutup kalau isinya tab kosong. Tab yang sedang mengerjakan sesuatu bisa tertinggal. |
