"""Penjaga alat browser (Claude in Chrome) untuk Jarvis.

Dipakai dua cara:
1. Diimpor jarvis.py: label aksi, log, baca permintaan izin, tulis izin sekali pakai.
2. Dijalankan Claude Code sebagai hook (lewat --settings) untuk semua alat mcp__claude-in-chrome__*:
   - PreToolUse memutuskan "allow" / "deny" untuk tiap aksi:
     * semua situs boleh; baca, klik, ketik, dan isi form langsung jalan.
     * kolom kata sandi, data kartu, dan data pribadi -> SELALU ditolak.
     * hanya kalau saklar "tanya dulu" nyala (env JARVIS_BROWSER_CONFIRM=1): aksi bayar, beli, kirim, hapus,
       posting, konfirmasi, transfer, atau mengirim form di halaman yang mengandung kata itu, serta
       JavaScript dan unggah file -> ditolak dan dicatat sebagai permintaan izin. Jarvis menanyakan ya/tidak
       lewat suara; kalau "ya", izin sekali pakai untuk aksi itu ditulis ke grants.json.
   - PostToolUse mencatat URL tiap tab, kata sensitif di halaman, dan label kolom (ref) dari read_page/find.
   Env: JARVIS_BROWSER_CONFIRM (1 = tanya dulu), JARVIS_BROWSER_STATE (folder state), JARVIS_BROWSER_LOG.
"""
import datetime
import json
import os
import re
import sys
import tempfile
from urllib.parse import urlsplit

CHROME_MCP = "mcp__claude-in-chrome__"
PRIVATE_DENIED = "Kolom kata sandi, data kartu, atau data pribadi tidak boleh diisi."
NEED_PERMISSION = "PERLU_IZIN"

# alat baca (juga didaftarkan di --allowedTools sebagai cadangan kalau hook tidak jalan)
READ_TOOLS = ("navigate", "get_page_text", "read_page", "find", "tabs_context_mcp", "tabs_create_mcp",
              "tabs_close_mcp", "list_connected_browsers", "read_console_messages")
CLICK_ACTIONS = {"left_click", "right_click", "double_click", "triple_click", "left_click_drag"}
ASK_TOOLS = {"javascript_tool", "file_upload", "upload_image"}   # ditanya kalau saklar "tanya dulu" nyala

ACTION_LABELS = {
    "left_click": "klik", "right_click": "klik kanan", "double_click": "klik ganda", "triple_click": "klik tiga kali",
    "left_click_drag": "menyeret", "type": "mengetik", "key": "menekan tombol", "hover": "mengarahkan kursor",
}
TOOL_LABELS = {
    "form_input": "mengisi form", "file_upload": "mengunggah file", "upload_image": "mengunggah gambar",
    "javascript_tool": "menjalankan JavaScript", "browser_batch": "menjalankan beberapa aksi",
    "gif_creator": "merekam GIF", "resize_window": "mengubah ukuran jendela", "switch_browser": "ganti browser",
}

# aksi yang tidak bisa dibatalkan (dicari di ringkasan aksi, dan di isi halaman untuk aksi kirim-form)
SENSITIVE_RE = re.compile(
    r"bayar|pembelian|\w*beli\b|kirim|hapus|posting|konfirmasi|transfer|\bpay|\bbuy\b|\bpurchas|\bcheck ?out"
    r"|\border\b|\bsend|\bsent\b|\bdelet|\bremov|\bpost\b|\bpublish|\bconfirm", re.I)
# belanja / pembayaran / transfer: SELALU ditolak, saklar "tanya dulu" mati pun
MONEY_RE = re.compile(
    r"bayar|pembelian|\w*beli\b|checkout|check ?out|keranjang|transfer|top ?up|isi saldo"
    r"|\bpay\b|\bpayment|\bbuy\b|\bpurchas|place order|order now|pesan sekarang|add to cart|\bcart\b",
    re.I)
MONEY_DENIED = "Belanja, pembayaran, dan transfer uang tidak boleh dilakukan Jarvis."
# tanda aksi mengirim form
SUBMIT_RE = re.compile(r"submit|kirim|\bsend|lanjut|continue|proceed|\bnext\b|\bplace\b|\bok\b|\bdone\b|selesai"
                       r"|\bsave\b|simpan|\bapply\b|terapkan", re.I)
# kolom / data pribadi: selalu ditolak saat diisi
PRIVATE_RE = re.compile(
    r"password|passwd|kata ?sandi|\bsandi\b|\bpin\b|\botp\b|\bcvv|\bcvc|kartu (?:kredit|debit)|(?:credit|debit) ?card"
    r"|card ?number|nomor kartu|\bkartu\b|rekening|account number|\biban\b|\bssn\b|\bnik\b|\bktp\b|passport"
    r"|paspor|tanggal lahir|date of birth|birth ?date|birthday|\bnpwp\b|e-?mail|nomor (?:hp|telepon|ponsel)"
    r"|phone|telepon|alamat rumah|alamat pengiriman|(?:shipping|billing|home|street) address", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?62|0)8\d{7,11}(?!\d)|(?<!\d)\+\d{9,15}(?!\d)")
DIGITS_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
TAB_LINE_RE = re.compile(r'tabId (\d+): "(.*?)" \("([^"]*)"\)')
REF_RE = re.compile(r"\[?(ref_\d+)\]?")
SITE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$")


# ----- URL -----
def short_name(tool_name):
    """'mcp__claude-in-chrome__navigate' -> 'navigate'."""
    return tool_name[len(CHROME_MCP):] if tool_name.startswith(CHROME_MCP) else tool_name


def normalize_site(s):
    """'https://www.Example.com/a?b' -> 'example.com'. Return '' kalau bukan nama situs."""
    s = str(s or "").strip().lower()
    if not s:
        return ""
    if "://" not in s:
        s = "//" + s
    try:
        host = (urlsplit(s).hostname or "").strip(".")
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host if SITE_RE.match(host) else ""


def host_of(url):
    url = str(url or "").strip()
    if not url or url in ("back", "forward"):
        return ""
    return normalize_site(url)


def safe_url(url):
    """URL untuk log: host + path, tanpa query dan fragmen (bisa berisi token atau data pribadi)."""
    url = str(url or "").strip()
    if url in ("back", "forward"):
        return url
    try:
        p = urlsplit(url if "://" in url else "https://" + url)
    except ValueError:
        return ""
    return (p.hostname or "") + (p.path or "")


def same_page(a, b):
    """True kalau dua URL menunjuk halaman yang sama (abaikan skema, query, garis miring akhir)."""
    return safe_url(a).rstrip("/") == safe_url(b).rstrip("/")


# ----- data pribadi dan aksi sensitif -----
def luhn_ok(digits):
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def private_value(text):
    """True kalau teks tampak data pribadi: email, nomor HP, nomor kartu (Luhn), NIK (16 digit)."""
    t = str(text or "")
    if EMAIL_RE.search(t) or PHONE_RE.search(t):
        return True
    for m in DIGITS_RE.finditer(t):
        d = re.sub(r"\D", "", m.group(0))
        if len(d) == 16 or (13 <= len(d) <= 19 and luhn_ok(d)):
            return True
    return False


def private_label(text):
    return bool(PRIVATE_RE.search(str(text or "")))


def sensitive_text(text):
    return bool(SENSITIVE_RE.search(str(text or "")))


# ----- state (folder JARVIS_BROWSER_STATE) -----
def state_dir():
    return os.environ.get("JARVIS_BROWSER_STATE") or ""


def load_json(name, default, folder=None):
    folder = folder if folder is not None else state_dir()
    if not folder:
        return default
    try:
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def save_json(name, data, folder=None):
    folder = folder if folder is not None else state_dir()
    if not folder:
        return
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(folder, name))


def add_request(req, folder=None):
    reqs = load_json("requests.json", [], folder)
    reqs.append(req)
    save_json("requests.json", reqs, folder)


def take_requests(folder=None):
    """Baca lalu kosongkan permintaan dari hook (dipakai Jarvis setelah satu giliran)."""
    reqs = load_json("requests.json", [], folder)
    save_json("requests.json", [], folder)
    return reqs


def grant(reqs, folder=None):
    """Izin sekali pakai untuk aksi yang ditanyakan (tool, action, host)."""
    grants = load_json("grants.json", [], folder)
    for r in reqs:
        if r.get("kind") == "izin":
            grants.append({"tool": r.get("tool"), "action": r.get("action", ""), "host": r.get("host", "")})
    save_json("grants.json", grants, folder)


def clear_grants(folder=None):
    save_json("grants.json", [], folder)


def consume_grant(tool, action, host, folder=None):
    grants = load_json("grants.json", [], folder)
    for i, g in enumerate(grants):
        if g.get("tool") == tool and g.get("action", "") == (action or "") and g.get("host", "") == (host or ""):
            del grants[i]
            save_json("grants.json", grants, folder)
            return True
    return False


def log_line(tool, action, url, status):
    path = os.environ.get("JARVIS_BROWSER_LOG")
    if not path:
        return
    row = " | ".join([datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tool or "-", action or "-",
                      url or "-", status])
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(row + "\n")
    except OSError:
        pass


# ----- keputusan -----
def action_label(tool_name, tool_input):
    """Teks pendek untuk konfirmasi suara, mis. 'klik: Sends the reply'. Tanpa isi form / teks ketikan."""
    name, inp = short_name(tool_name), tool_input or {}
    if name == "computer":
        label = ACTION_LABELS.get(inp.get("action"), str(inp.get("action") or "aksi"))
    else:
        label = TOOL_LABELS.get(name, name.replace("_", " "))
    summary = " ".join(str(inp.get("action_summary") or "").split())[:80]
    return f"{label}: {summary}" if summary else label


def _tab(tabs, tab_id):
    return tabs.get(str(tab_id)) if tab_id is not None else None


def check(name, inp, confirm, tabs, allow_grant=True, folder=None):
    """Satu aksi -> (keputusan, jenis, alasan). keputusan: "allow" / "deny"; jenis: "" / "pribadi" / "belanja" / "izin".
    confirm = saklar "tanya dulu sebelum bayar/kirim/hapus/posting". `tabs` diperbarui untuk aksi berikutnya."""
    inp = inp or {}
    tab_id = inp.get("tabId")
    tab = _tab(tabs, tab_id)
    if name == "navigate":
        url = str(inp.get("url") or "")
        host = host_of(url)
        if tab_id is not None and host and (tab is None or not same_page(tab.get("url"), url)):
            tabs[str(tab_id)] = {"host": host, "url": safe_url(url), "sensitive": sensitive_text(url), "refs": {}}
        return "allow", "", ""
    if tab is None:
        tab = {}
    action = inp.get("action") if name == "computer" else ""
    summary = str(inp.get("action_summary") or "")
    ref_label = (tab.get("refs") or {}).get(str(inp.get("ref") or ""), "")

    # data pribadi: selalu ditolak, tanpa pengecualian
    if name == "form_input" and (private_label(ref_label) or private_label(summary) or private_value(inp.get("value"))):
        return "deny", "pribadi", PRIVATE_DENIED
    if name == "computer" and action == "type" and (tab.get("focus_private") or private_label(summary)
                                                    or private_value(inp.get("text"))):
        return "deny", "pribadi", PRIVATE_DENIED
    if name == "computer" and action in CLICK_ACTIONS and tab_id is not None:
        tabs.setdefault(str(tab_id), tab)["focus_private"] = private_label(ref_label) or private_label(summary)

    # belanja / bayar / transfer: selalu ditolak, tanpa izin sekali pakai
    if name == "computer" and action in CLICK_ACTIONS | {"key"} and MONEY_RE.search(summary + " " + ref_label):
        return "deny", "belanja", MONEY_DENIED
    if name == "form_input" and MONEY_RE.search(summary):
        return "deny", "belanja", MONEY_DENIED

    if not confirm:                                   # saklar mati: semua aksi lain langsung jalan
        return "allow", "", ""
    ask = name in ASK_TOOLS
    if name == "computer" and action in CLICK_ACTIONS | {"key"}:
        submit = (action == "key" and re.search(r"\b(return|enter)\b", str(inp.get("text") or ""), re.I)) \
            or SUBMIT_RE.search(summary + " " + ref_label)
        blind = action != "key" and not summary.strip() and not ref_label    # klik tanpa keterangan
        ask = sensitive_text(summary + " " + ref_label) or bool((submit or blind) and tab.get("sensitive"))
    if ask:
        if allow_grant and consume_grant(name, action, tab.get("host", ""), folder):
            return "allow", "", "izin sekali pakai"
        return "deny", "izin", (f"{NEED_PERMISSION}: {action_label(name, inp)}. Berhenti dan minta izin pengguna. "
                                "Setelah diizinkan, jalankan aksi ini sendiri (bukan di browser_batch).")
    return "allow", "", ""


def decide(tool_name, tool_input, confirm, tabs, folder=None):
    """Keputusan untuk satu pemanggilan alat (termasuk browser_batch). Return (keputusan, jenis, alasan, aksi)
    dengan aksi = (nama, input) yang menentukan keputusan (untuk permintaan izin)."""
    name, inp = short_name(tool_name), tool_input or {}
    if name != "browser_batch":
        d, kind, reason = check(name, inp, confirm, tabs, folder=folder)
        return d, kind, reason, (name, inp)
    items = [(short_name(a.get("name", "")), a.get("input") or {})
             for a in inp.get("actions") or [] if isinstance(a, dict)]
    for n, i in items:                                # aksi yang perlu izin tidak boleh lewat batch
        d, kind, reason = check(n, i, confirm, tabs, allow_grant=False, folder=folder)
        if d == "deny":
            return d, kind, reason, (n, i)
    return "allow", "", "", None


def log_items(tool_name, tool_input):
    """Daftar (alat, jenis aksi, url aman) untuk logs\\jarvis_browser.log. Tanpa isi form / teks ketikan."""
    name, inp = short_name(tool_name), tool_input or {}
    if name == "browser_batch":
        out = []
        for a in inp.get("actions") or []:
            if isinstance(a, dict):
                out += log_items(a.get("name", ""), a.get("input") or {})
        return out
    action = inp.get("action") if name == "computer" else ""
    url = safe_url(inp.get("url")) if inp.get("url") else ""
    return [(name, action or "", url)]


# ----- hasil alat (PostToolUse) -----
def response_text(resp):
    """Semua teks di tool_response (string, atau daftar/blok berisi 'text')."""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, list):
        return "\n".join(response_text(x) for x in resp)
    if isinstance(resp, dict):
        if "text" in resp and isinstance(resp["text"], str):
            return resp["text"]
        return "\n".join(response_text(v) for v in resp.values() if isinstance(v, (str, list, dict)))
    return ""


def observe(name, inp, text, tabs):
    """Perbarui state tab dari hasil alat: URL tiap tab, kata sensitif, label ref."""
    for tab_id, title, url in TAB_LINE_RE.findall(text):
        tab = tabs.setdefault(tab_id, {"refs": {}})
        su = safe_url(url)
        if not same_page(tab.get("url"), su):        # halaman berganti: lupakan ref dan tanda sensitif lama
            tab.update(url=su, refs={}, focus_private=False, sensitive=False)
        tab["host"] = host_of(url) if url.startswith(("http://", "https://")) else ""
        tab["sensitive"] = tab.get("sensitive") or sensitive_text(title + " " + url)
    tab_id = (inp or {}).get("tabId")
    if tab_id is None:
        m = re.search(r"Executed on tabId: (\d+)", text)
        tab_id = m.group(1) if m else None
    tab = _tab(tabs, tab_id)
    if tab is None:
        return
    if name in ("get_page_text", "read_page", "find") and sensitive_text(text):
        tab["sensitive"] = True
    if name in ("read_page", "find"):
        refs = tab.setdefault("refs", {})
        for line in text.splitlines():
            for ref in REF_RE.findall(line):
                refs[ref] = line.strip()[:200]


def confirm_from_env():
    return os.environ.get("JARVIS_BROWSER_CONFIRM") == "1"


def main():
    event = "PreToolUse"
    try:
        data = json.load(sys.stdin)
        event = data.get("hook_event_name", "PreToolUse")
        tool, inp = data.get("tool_name", ""), data.get("tool_input") or {}
        tabs = load_json("tabs.json", {})
        if event == "PostToolUse":
            name = short_name(tool)
            if name == "browser_batch":
                text = response_text(data.get("tool_response"))
                for a in inp.get("actions") or []:
                    if isinstance(a, dict):
                        observe(short_name(a.get("name", "")), a.get("input") or {}, text, tabs)
            else:
                observe(name, inp, response_text(data.get("tool_response")), tabs)
            save_json("tabs.json", tabs)
            return 0
        decision, kind, reason, act = decide(tool, inp, confirm_from_env(), tabs)
        save_json("tabs.json", tabs)
        if decision == "deny" and act:
            n, i = act
            host = (_tab(tabs, i.get("tabId")) or {}).get("host", "")
            action = i.get("action") if n == "computer" else ""
            add_request({"kind": kind, "tool": n, "action": action or "", "host": host,
                         "label": action_label(n, i) if kind == "izin" else action_label(n, {"action": action})})
            log_line(n, action, host, f"HOOK DITOLAK ({kind})")
        elif reason == "izin sekali pakai":
            log_line(short_name(tool), inp.get("action", ""), "", "HOOK: izin sekali pakai dipakai")
    except Exception as e:                         # gagal membaca: tolak (lebih aman daripada lolos)
        if event == "PostToolUse":
            return 0
        decision, reason = "deny", f"browser_guard error: {type(e).__name__}"
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                             "permissionDecisionReason": reason or decision}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
