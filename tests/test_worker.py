"""Runs the remote worker against a mock OpenAI TTS server, speaking the game's worker protocol."""
import io
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from qwen_patcher import build_worker  # noqa: E402
from qwen_patcher.remote import test_server  # noqa: E402


def write_str(s):
    data, n, prefix = s.encode(), len(s.encode()), b""
    while True:
        byte, n = n & 0x7F, n >> 7
        prefix += bytes([byte | (0x80 if n else 0)])
        if not n:
            return prefix + data


class MockServer(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        MockServer.requests.append((self.headers.get("Authorization"), body))
        if body["input"] == "fail":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"boom")
            return
        if body["response_format"] == "pcm":
            data = b"".join(struct.pack("<h", int(8000 * math.sin(i / 10.0))) for i in range(24000))
        else:  # 1 s, 22050 Hz stereo -> must arrive as ~24000 mono samples
            buf = io.BytesIO()
            w = wave.open(buf, "wb")
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(struct.pack("<hh", 16000, -16000) * 22050)
            w.close()
            data = buf.getvalue()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class WorkerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.exe = os.path.join(cls.dir, "QwenTtsWorker.exe")
        build_worker(cls.exe)
        cls.server = HTTPServer(("127.0.0.1", 0), MockServer)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.config = {
            "url": "http://127.0.0.1:%d/v1/audio/speech" % cls.server.server_address[1],
            "api_key": "secret", "model": "m", "voice": "fallback", "response_format": "wav",
            "send_reference_audio": True, "extra_body": {"task_type": "Base", "x_vector_only_mode": True},
            "voice_map": {}, "dump_references": True,
        }

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        MockServer.requests = []

    def start(self, **overrides):
        config = dict(self.config, **overrides)
        with open(os.path.join(self.dir, "qwen-remote.json"), "w") as f:
            json.dump(config, f)
        p = subprocess.Popen([self.exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.addCleanup(p.kill)
        p.stdin.write(struct.pack("<i", 1) + write_str("C:/missing/model.gguf") + write_str("CUDA"))
        p.stdin.flush()
        return p

    def read_int(self, p):
        return struct.unpack("<i", p.stdout.read(4))[0]

    def read_str(self, p):
        n = shift = 0
        while True:
            b = p.stdout.read(1)[0]
            n |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                return p.stdout.read(n).decode()

    def loaded(self, p):
        self.assertEqual((self.read_int(p), self.read_int(p), self.read_str(p)), (1, 2, "cpu"))

    def synth(self, p, text, reference):
        msg = struct.pack("<i", 2) + write_str(text) + write_str("German") + struct.pack("<i", len(reference))
        msg += struct.pack("<%df" % len(reference), *reference)
        p.stdin.write(msg)
        p.stdin.flush()
        total = 0
        while True:
            kind = self.read_int(p)
            if kind == 3:
                return total
            if kind == 4:
                raise IOError(self.read_str(p))
            n = self.read_int(p)
            samples = struct.unpack("<%df" % n, p.stdout.read(n * 4))
            self.assertTrue(all(-1 <= s <= 1 for s in samples))
            total += n

    reference = [0.1 * math.sin(i / 7.0) for i in range(24000)]

    def test_wav_resampled_and_reference_reused(self):
        p = self.start()
        self.loaded(p)
        self.assertAlmostEqual(self.synth(p, "Hallo Welt", self.reference), 24000, delta=2)
        self.assertAlmostEqual(self.synth(p, "Nochmal", []), 24000, delta=2)
        auth, body = MockServer.requests[0]
        self.assertEqual(auth, "Bearer secret")
        self.assertEqual((body["input"], body["language"], body["voice"], body["task_type"]),
                         ("Hallo Welt", "German", "fallback", "Base"))
        self.assertTrue(body["ref_audio"].startswith("data:audio/wav;base64,UklGR"))
        self.assertEqual(MockServer.requests[1][1]["ref_audio"], body["ref_audio"])

    def test_long_text_is_sent_sentence_by_sentence(self):
        p = self.start()
        self.loaded(p)
        text = ("Hello, this is your bank calling about a suspicious payment. We need to verify your account "
                "right now! Can you read me the code we just sent? Thank you.")
        self.assertAlmostEqual(self.synth(p, text, self.reference), 2 * 24000, delta=4)
        inputs = [body["input"] for _, body in MockServer.requests]
        self.assertEqual(inputs, ["Hello, this is your bank calling about a suspicious payment. We need to verify your "
                                  "account right now!", "Can you read me the code we just sent? Thank you."])
        self.assertTrue(all(len(i) <= 120 for i in inputs))

    def test_splitting_can_be_disabled(self):
        p = self.start(split_sentences=False)
        self.loaded(p)
        self.synth(p, "One. Two. Three.", self.reference)
        self.assertEqual([body["input"] for _, body in MockServer.requests], ["One. Two. Three."])

    def test_raw_base64_reference_in_custom_field(self):
        p = self.start(reference_audio_field="audio_sample", reference_audio_encoding="base64", extra_body={})
        self.loaded(p)
        self.synth(p, "Hallo", self.reference)
        body = MockServer.requests[0][1]
        self.assertTrue(body["audio_sample"].startswith("UklGR"))
        self.assertNotIn("ref_audio", body)
        self.assertNotIn("task_type", body)

    def test_server_error_is_reported_and_worker_survives(self):
        p = self.start()
        self.loaded(p)
        with self.assertRaisesRegex(IOError, "HTTP 500: boom"):
            self.synth(p, "fail", self.reference)
        self.assertGreater(self.synth(p, "geht wieder", []), 0)

    def test_pcm_stream_and_voice_map(self):
        p = self.start()
        self.loaded(p)
        self.synth(p, "Referenz", self.reference)
        voices = os.listdir(os.path.join(self.dir, "remote-voices"))
        self.assertEqual(len(voices), 1)
        voice_hash = voices[0][:-4]
        p = self.start(response_format="pcm", voice_map={voice_hash: "jake"})
        self.loaded(p)
        self.assertEqual(self.synth(p, "Streaming", self.reference), 24000)
        self.assertEqual(MockServer.requests[-1][1]["voice"], "jake")

    def test_offline_server_fails_at_load(self):
        p = self.start(url="http://127.0.0.1:1/v1/audio/speech")
        self.assertEqual(self.read_int(p), 4)
        self.assertIn("not reachable", self.read_str(p))

    def test_connection_test_helper(self):
        self.assertTrue(test_server(self.config).startswith("OK"))
        with self.assertRaises(IOError):
            test_server(dict(self.config, url=self.config["url"]), text="fail")


if __name__ == "__main__":
    unittest.main()
