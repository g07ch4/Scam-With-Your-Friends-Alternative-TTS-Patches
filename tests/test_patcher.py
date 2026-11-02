"""Patches a copy of the real game files. Needs an installed game (auto-detected or SWYF_GAME_DIR)."""
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from qwen_patcher import Game, Options, PatchError, build_worker, find_game_dirs  # noqa: E402
from qwen_patcher.core import ELIGIBLE_SIG, OFF_GPU_AND, OFF_RAM, OFF_THREADS, OFF_VRAM, sha256  # noqa: E402

SOURCE = os.environ.get("SWYF_GAME_DIR") or next(iter(find_game_dirs()), None)
FILES = ("Scam With Your Friends_Data/Managed/Assembly-CSharp.dll",
         "Scam With Your Friends_Data/StreamingAssets/kolkata-qwen-runtime/QwenTtsWorker.exe",
         "Scam With Your Friends_Data/StreamingAssets/kolkata-qwen-runtime/runtime-manifest.json")


@unittest.skipUnless(SOURCE, "game not installed")
class PatcherTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.worker = os.path.join(cls.tmp, "QwenRemoteWorker.exe")
        build_worker(cls.worker)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.root = tempfile.mkdtemp(dir=self.tmp)
        for rel in FILES:
            os.makedirs(os.path.dirname(os.path.join(self.root, rel)), exist_ok=True)
            shutil.copy2(os.path.join(SOURCE, rel), os.path.join(self.root, rel))
        self.game = Game(self.root)
        self.originals = {rel: sha256(os.path.join(SOURCE, rel)) for rel in FILES}
        self.quiet = lambda line: None

    def test_lowreq_values(self):
        self.game.install(Options(lowreq=True, vram=2048, ram=6000, avail=2500, threads=1), log=self.quiet)
        with open(self.game.dll, "rb") as f:
            data = f.read()
        with open(self.game.dll + ".orig", "rb") as f:
            orig = f.read()
        base = orig.find(ELIGIBLE_SIG)
        self.assertEqual(struct.unpack_from("<i", data, base + OFF_VRAM)[0], 2048)
        self.assertEqual(struct.unpack_from("<i", data, base + OFF_RAM)[0], 6000)
        self.assertEqual(data[base + OFF_THREADS], 0x17)
        self.assertEqual(data[base + OFF_GPU_AND + 1], 0x06)  # GPU still required
        changed = [i for i, (a, b) in enumerate(zip(orig, data)) if a != b]
        self.assertTrue(changed and all(base <= i < base + 0x9D for i in changed))  # only inside HardwareEligible
        self.assertEqual(self.game.status()[0], "patched")

    def test_remote_installs_worker_and_manifest(self):
        config = {"url": "http://192.168.1.2:8000/v1/audio/speech"}
        self.game.install(Options(remote=True), remote_config=config, worker_exe=self.worker, log=self.quiet)
        self.assertEqual(sha256(self.game.worker), sha256(self.worker))
        with open(self.game.manifest) as f:
            entries = {e["path"]: e["sha256"] for e in json.load(f)["files"]}
        self.assertEqual(entries["QwenTtsWorker.exe"], sha256(self.worker))
        with open(self.game.config) as f:
            self.assertEqual(json.load(f), config)

    def test_switching_options_starts_from_original(self):
        self.game.install(Options(remote=True), remote_config={"url": "http://x:1/"}, worker_exe=self.worker,
                          log=self.quiet)
        self.game.install(Options(lowreq=True), log=self.quiet)
        self.assertEqual(sha256(self.game.worker), self.originals[FILES[1]])
        self.assertEqual(sha256(self.game.manifest), self.originals[FILES[2]])

    def test_restore_is_bit_identical(self):
        self.game.install(Options(lowreq=True, allow_cpu=True, remote=True), remote_config={"url": "http://x:1/"},
                          worker_exe=self.worker, log=self.quiet)
        self.game.uninstall(log=self.quiet)
        for rel in FILES:
            self.assertEqual(sha256(os.path.join(self.root, rel)), self.originals[rel], rel)
        self.assertEqual(self.game.status()[0], "original")

    def test_game_update_is_detected_and_repatched(self):
        self.game.install(Options(lowreq=True), log=self.quiet)
        shutil.copy2(os.path.join(SOURCE, FILES[0]), self.game.dll)  # Steam "verify files"
        self.assertEqual(self.game.status()[0], "reverted")
        self.game.install(Options(lowreq=True), log=self.quiet)
        self.assertEqual(self.game.status()[0], "patched")
        self.assertEqual(sha256(self.game.dll + ".orig"), self.originals[FILES[0]])

    def test_unknown_dll_is_rejected_untouched(self):
        with open(self.game.dll, "r+b") as f:
            data = f.read()
            f.seek(data.find(ELIGIBLE_SIG))
            f.write(b"\0" * len(ELIGIBLE_SIG))
        before = sha256(self.game.dll)
        with self.assertRaises(PatchError):
            self.game.install(Options(lowreq=True), log=self.quiet)
        self.assertEqual(sha256(self.game.dll), before)


if __name__ == "__main__":
    unittest.main()
