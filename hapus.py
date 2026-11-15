"""Hapus file atau folder atas izin pengguna (lewat suara).

Claude tidak pernah menghapus sendiri: perintah hapus (rm, del, Remove-Item, ...) tetap ada di deny_list.
Alurnya:
1. Claude mencari path lengkapnya, lalu menulis satu baris "HAPUS: <path lengkap>" per item di jawabannya.
2. Jarvis memeriksa path itu (harus ada, path lengkap, tanpa wildcard, bukan folder sistem / folder penting),
   lalu bertanya lewat suara: "Yakin hapus ...? Katakan ya atau tidak."
3. Kalau "ya", Jarvis sendiri yang memindahkan item ke Recycle Bin (masih bisa dikembalikan).
"""
import os
import re
import sys

HAPUS_RE = re.compile(r"^[ \t]*[*_`]*[ \t]*HAPUS[ \t]*:[ \t]*[*_`]*[ \t]*(.*?)[ \t]*$", re.I | re.M)
MAX_TARGETS = 20               # paling banyak item dalam satu kali minta izin
MAX_COUNT = 100_000            # berhenti menghitung isi folder setelah sekian file

PROMPT = (
    "Menghapus file atau folder: JANGAN jalankan perintah hapus sendiri (rm, del, Remove-Item, dll pasti "
    "diblokir). Cari dan pastikan dulu path lengkapnya, lalu di akhir jawaban tambahkan satu baris "
    "'HAPUS: <path lengkap>' untuk tiap item, tanpa wildcard, maksimal 20 baris. Jarvis yang menanyakan izin "
    "ke pengguna lalu memindahkannya ke Recycle Bin. UCAPAN cukup misalnya 'Ketemu, tinggal konfirmasi.'. "
    "Kalau targetnya tidak jelas atau banyak yang mirip, tanya dulu dan jangan tulis baris HAPUS."
)
# pengingat per perintah (system prompt tidak berubah di percakapan yang di-resume)
REMINDER = " (Kalau diminta menghapus: jangan jalankan perintah hapus, tulis baris 'HAPUS: <path lengkap>'.)"
DELETE_WORDS_RE = re.compile(r"\b(hapus\w*|menghapus|dihapus|delete\w*|buang\w*|singkirkan|remove)\b", re.I)


def wants_delete(text):
    """True kalau ucapan pengguna kemungkinan minta menghapus sesuatu."""
    return bool(DELETE_WORDS_RE.search(text or ""))


def _clean(path):
    path = path.strip().strip("`*_").strip()
    if len(path) >= 2 and path[0] == path[-1] and path[0] in "\"'":
        path = path[1:-1].strip()
    return path


def parse_targets(text):
    """Path dari baris 'HAPUS: ...' di jawaban Claude (urutan asli, tanpa duplikat)."""
    out = []
    for m in HAPUS_RE.finditer(text or ""):
        p = _clean(m.group(1))
        if p and p.strip(" .-") and p not in out:
            out.append(p)
    return out


def strip_targets(text):
    """Jawaban tanpa baris 'HAPUS: ...' (supaya tidak ikut tampil di LAYAR atau dibacakan)."""
    return HAPUS_RE.sub("", text or "").strip()


def _norm(path):
    return os.path.normcase(os.path.normpath(os.path.realpath(path)))


def _inside(path, folder):
    """True kalau path sama dengan folder atau ada di dalamnya (keduanya sudah dinormalkan)."""
    return path == folder or path.startswith(folder.rstrip("\\/") + os.sep)


def protected_paths(app_dir=None):
    """(folder yang isinya tidak boleh disentuh, folder yang dirinya sendiri tidak boleh dihapus)."""
    env = os.environ.get
    inside = [env("SystemRoot") or env("windir"), env("ProgramFiles"), env("ProgramFiles(x86)"),
              env("ProgramW6432")]
    if os.name != "nt":
        inside += ["/bin", "/boot", "/etc", "/lib", "/lib64", "/sbin", "/usr", "/proc", "/sys", "/dev"]
    home = os.path.expanduser("~")
    itself = [home, env("ProgramData"), env("APPDATA"), env("LOCALAPPDATA"), env("USERPROFILE"),
              os.path.join(home, ".claude")]
    itself += [os.path.join(home, d) for d in ("Desktop", "Documents", "Downloads", "Pictures", "Music",
                                               "Videos", "AppData", "OneDrive")]
    if app_dir:
        itself.append(app_dir)
    return ([_norm(p) for p in inside if p], [_norm(p) for p in itself if p])


def check(path, protected):
    """Return alasan (teks) kalau path tidak boleh dihapus, atau None kalau boleh."""
    if any(ch in path for ch in "*?<>|\n\r"):
        return "pakai wildcard atau karakter aneh"
    if not os.path.isabs(path):
        return "bukan path lengkap"
    if not os.path.lexists(path):
        return "tidak ada"
    p = _norm(path)
    if os.path.dirname(p) == p:
        return "itu akar drive"
    inside, itself = protected
    if any(_inside(p, f) for f in inside):
        return "folder sistem"
    for f in itself:
        if p == f:
            return "folder penting"
        if _inside(f, p):
            return "berisi folder penting"
    return None


def check_all(paths, protected):
    """Return (daftar path yang boleh, daftar (path, alasan) yang ditolak)."""
    ok, bad = [], []
    for p in paths:
        if len(ok) >= MAX_TARGETS:
            bad.append((p, f"lebih dari {MAX_TARGETS} item sekaligus"))
            continue
        why = check(p, protected)
        if why:
            bad.append((p, why))
        elif p not in ok:
            ok.append(p)
    return ok, bad


def folder_stats(path):
    """(jumlah file, total byte) isi folder; berhenti menghitung setelah MAX_COUNT file."""
    n = size = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            n += 1
            try:
                size += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
            if n >= MAX_COUNT:
                return n, size
    return n, size


def human_size(b):
    for unit in ("byte", "KB", "MB", "GB"):
        if b < 1024 or unit == "GB":
            return f"{b:.0f} {unit}" if unit == "byte" else f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} GB"


def label(path):
    """'folder build' / 'file laporan.txt' (untuk diucapkan)."""
    name = os.path.basename(os.path.normpath(path)) or path
    return ("folder " if os.path.isdir(path) and not os.path.islink(path) else "file ") + name


def detail(path):
    """Satu baris untuk layar: jenis, path, isi/ukuran."""
    if os.path.isdir(path) and not os.path.islink(path):
        n, size = folder_stats(path)
        more = "+" if n >= MAX_COUNT else ""
        return f"folder  {path}  ({n}{more} file, {human_size(size)})"
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    return f"file    {path}  ({human_size(size)})"


def spoken(paths):
    """Kalimat pendek untuk konfirmasi suara."""
    if len(paths) == 1:
        p = paths[0]
        if os.path.isdir(p) and not os.path.islink(p):
            n, _ = folder_stats(p)
            return f"{label(p)}, isinya {n} file" if n else f"{label(p)}, folder kosong"
        return label(p)
    if len(paths) <= 3:
        names = [label(p) for p in paths]
        return ", ".join(names[:-1]) + ", dan " + names[-1]
    return f"{len(paths)} item ini, daftarnya di layar"


def _trash_windows(path):
    """Pindahkan ke Recycle Bin lewat SHFileOperationW (FOF_ALLOWUNDO), tanpa jendela konfirmasi."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE = 3
    FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW(hwnd=None, wFunc=FO_DELETE, pFrom=os.path.abspath(path) + "\0", pTo=None,
                         fFlags=FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0:
        raise OSError(f"Windows menolak (kode {rc:#x}); mungkin file sedang dipakai atau tidak ada izin")
    if op.fAnyOperationsAborted:
        raise OSError("dibatalkan Windows")


def to_trash(path):
    """Pindahkan satu file/folder ke Recycle Bin (atau tempat sampah sistem lain kalau ada send2trash)."""
    if sys.platform == "win32":
        return _trash_windows(path)
    try:
        from send2trash import send2trash
    except ImportError:
        raise OSError("Recycle Bin hanya didukung di Windows (atau pasang paket send2trash)") from None
    send2trash(path)


def delete(paths, protected, trash=None):
    """Periksa ulang lalu pindahkan ke Recycle Bin. Return (berhasil, [(path, alasan gagal)])."""
    trash = trash or to_trash
    done, failed = [], []
    for p in paths:
        why = check(p, protected)          # bisa berubah sejak ditanya (dihapus/dipindah orang lain)
        if why:
            failed.append((p, why))
            continue
        try:
            trash(p)
        except Exception as e:             # noqa: BLE001 - alasan apa pun dilaporkan ke pengguna
            failed.append((p, str(e) or e.__class__.__name__))
            continue
        if os.path.lexists(p):
            failed.append((p, "masih ada setelah dihapus"))
        else:
            done.append(p)
    return done, failed
