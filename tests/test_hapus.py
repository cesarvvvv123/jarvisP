"""Tes hapus file/folder atas izin, dan tunggu lebih lama kalau ucapan berakhir "euuu"
(tanpa mic, tanpa Claude; Recycle Bin diganti fungsi palsu).

Pakai:  python tests\\test_hapus.py
"""
import os
import shutil
import sys
import tempfile
import threading
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import sounddevice  # noqa: F401
except Exception:                       # tanpa PortAudio (mis. di CI): cukup modul kosong
    sys.modules["sounddevice"] = types.ModuleType("sounddevice")
import hapus  # noqa: E402
import jarvis  # noqa: E402


def fake_trash(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


class FakeUI:
    def __init__(self):
        self.logs = []

    def log(self, text, tag="sys"):
        self.logs.append((tag, text))

    def __getattr__(self, name):
        return lambda *a, **k: None


class FakeSpeech:
    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)

    say_answer = say


def bare_jarvis(work_dir):
    j = jarvis.Jarvis.__new__(jarvis.Jarvis)
    j.ui = FakeUI()
    j.settings = dict(jarvis.DEFAULTS, work_dir=work_dir, projects={})
    j.tm, j.busy, j.cur_sp, j.pending = {}, False, None, []
    j.hold_lock, j.hold_text, j.hold_notes, j.hold_dur, j.hold_timer = threading.Lock(), [], [], 0.0, None
    j.listener_on = False
    j.spoken, j.turns = [], []
    j.speak = j.spoken.append
    j.run_turn = lambda text, **k: j.turns.append(text)
    j.record = lambda *a, **k: None
    return j


class TestParse(unittest.TestCase):
    def test_baris_hapus_dibaca_dan_dibuang_dari_layar(self):
        ans = ("UCAPAN: Ketemu, tinggal konfirmasi.\nLAYAR: dua file lama\n"
               "HAPUS: C:\\Users\\a\\Downloads\\lama.zip\n**HAPUS:** \"D:\\data\\folder lama\"\n")
        self.assertEqual(hapus.parse_targets(ans),
                         ["C:\\Users\\a\\Downloads\\lama.zip", "D:\\data\\folder lama"])
        ucap, layar, _ = jarvis.parse_reply(ans)
        self.assertEqual(ucap, "Ketemu, tinggal konfirmasi.")
        self.assertEqual(layar, "dua file lama")

    def test_minta_hapus_dikenali(self):
        self.assertTrue(hapus.wants_delete("tolong hapus folder build"))
        self.assertTrue(hapus.wants_delete("hapusin file itu"))
        self.assertFalse(hapus.wants_delete("buka kalkulator"))


class TestCheck(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.file = os.path.join(self.dir, "a.txt")
        open(self.file, "w").close()
        self.prot = hapus.protected_paths(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_aturan(self):
        self.assertIsNone(hapus.check(self.file, self.prot))
        self.assertIsNone(hapus.check(self.dir, self.prot))
        self.assertEqual(hapus.check("a.txt", self.prot), "bukan path lengkap")
        self.assertEqual(hapus.check(os.path.join(self.dir, "*.txt"), self.prot), "pakai wildcard atau karakter aneh")
        self.assertEqual(hapus.check(os.path.join(self.dir, "tidak_ada"), self.prot), "tidak ada")
        self.assertEqual(hapus.check(os.path.abspath(os.sep), self.prot), "itu akar drive")
        self.assertEqual(hapus.check(os.path.expanduser("~"), self.prot), "folder penting")
        self.assertEqual(hapus.check(jarvis.APP_DIR, self.prot), "folder penting")
        self.assertEqual(hapus.check(os.path.dirname(jarvis.APP_DIR), self.prot), "berisi folder penting")

    def test_hapus_ke_tempat_sampah(self):
        done, failed = hapus.delete([self.file, os.path.join(self.dir, "x")], self.prot, trash=fake_trash)
        self.assertEqual(done, [self.file])
        self.assertEqual(failed, [(os.path.join(self.dir, "x"), "tidak ada")])
        self.assertFalse(os.path.exists(self.file))


class TestAlurIzin(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.target = os.path.join(self.dir, "build")
        os.makedirs(self.target)
        open(os.path.join(self.target, "x.bin"), "w").close()
        self.j = bare_jarvis(self.dir)
        self.old = hapus.to_trash
        hapus.to_trash = fake_trash

    def tearDown(self):
        hapus.to_trash = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def ask(self):
        sp = FakeSpeech()
        self.j.ask_delete(f"UCAPAN: Ketemu.\nLAYAR: -\nHAPUS: {self.target}", sp)
        return sp

    def answer(self, text):
        self.j.hold_text = [text]
        self.j.dispatch()

    def test_ya_menghapus(self):
        sp = self.ask()
        self.assertEqual(self.j.pending, [("hapus", self.target)])
        self.assertIn("Yakin hapus folder build, isinya 1 file?", sp.said[0])
        self.assertTrue(os.path.exists(self.target))          # belum dihapus sebelum diizinkan
        self.answer("euuu ya")
        self.assertFalse(os.path.exists(self.target))
        self.assertEqual(self.j.pending, [])
        self.assertIn("Recycle Bin", self.j.spoken[-1])

    def test_tidak_membatalkan(self):
        self.ask()
        self.answer("jangan")
        self.assertTrue(os.path.exists(self.target))
        self.assertEqual(self.j.pending, [])

    def test_cuma_euuu_tidak_menjawab(self):
        self.ask()
        self.answer("euuuu...")
        self.assertTrue(os.path.exists(self.target))
        self.assertEqual(self.j.pending, [("hapus", self.target)])   # masih menunggu ya/tidak

    def test_folder_penting_ditolak(self):
        sp = FakeSpeech()
        self.j.ask_delete(f"UCAPAN: Oke.\nLAYAR: -\nHAPUS: {os.path.expanduser('~')}", sp)
        self.assertEqual(self.j.pending, [])
        self.assertIn("nggak bisa", sp.said[0])


class TestKataRagu(unittest.TestCase):
    def test_variasi_euuu(self):
        for w in ("euuu", "euuuuuuu", "Eee...", "emm,", "hmmm", "ehm", "anu", "eu"):
            self.assertTrue(jarvis.is_filler(w), w)
        for w in ("ekor", "dan", "atau", "menu", "email", "ya"):
            self.assertFalse(jarvis.is_filler(w), w)

    def test_buang_dari_perintah(self):
        self.assertEqual(jarvis.strip_fillers("buka folder euuu, build"), "buka folder build")
        self.assertEqual(jarvis.strip_fillers("Euuuu..."), "")

    def test_tunggu_lebih_lama(self):
        j = bare_jarvis(tempfile.gettempdir())
        biasa, sambung, ragu = (j.hold_delay(t) for t in ("buka kalkulator", "buka kalkulator atau",
                                                          "buka kalkulator dan euuuuu"))
        self.assertEqual(biasa, 0)
        self.assertAlmostEqual(sambung, 0.7)
        self.assertAlmostEqual(ragu, 3.0)


if __name__ == "__main__":
    unittest.main()
