"""Gladia speech recognition: the worker against a mock Gladia API (HTTP + WebSocket), speaking the
game's speech-helper protocol, and the patch against a copy of the real game files."""
import base64
import hashlib
import json
import math
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from qwen_patcher import build_worker, find_game_dirs  # noqa: E402
from qwen_patcher.core import sha256  # noqa: E402
from qwen_patcher.paths import STT_WORKER_SOURCE  # noqa: E402
from qwen_patcher.stt import SttGame, SttOptions, test_key  # noqa: E402

KEY = "test-key"


def text(s):
    data = s.encode("utf-8")
    return struct.pack("<i", len(data)) + data


class Gladia(object):
    """Shared state of the mock API."""
    uploads = []
    jobs = {}
    live_audio = []
    polls = 0


class MockApi(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        return self.rfile.read(int(self.headers.get("Content-Length", 0)))

    def do_POST(self):
        body = self.body()
        if self.headers.get("x-gladia-key") != KEY:
            return self.reply(401, {"statusCode": 401, "message": "gladia key not found"})
        if self.path == "/v2/upload":
            assert self.headers["Content-Type"].startswith("multipart/form-data; boundary=")
            wav = body[body.index(b"RIFF"):body.rindex(b"\r\n--")]
            Gladia.uploads.append(wav)
            return self.reply(200, {"audio_url": "http://mock/file/%d" % (len(Gladia.uploads) - 1)})
        if self.path == "/v2/pre-recorded":
            req = json.loads(body)
            job = str(len(Gladia.jobs))
            Gladia.jobs[job] = req
            return self.reply(201, {"id": job, "result_url": "http://mock/v2/transcription/" + job})
        if self.path.startswith("/v2/live"):
            req = json.loads(body)
            Gladia.jobs["live"] = req
            port = self.server.ws_port
            return self.reply(201, {"id": "live", "url": "ws://127.0.0.1:%d/v2/live?token=abc" % port})
        self.reply(404, {})

    def do_GET(self):
        if self.headers.get("x-gladia-key") != KEY:
            return self.reply(401, {})
        job = self.path.rsplit("/", 1)[-1]
        req = Gladia.jobs.get(job)
        if req is None:
            return self.reply(404, {})
        Gladia.polls += 1
        if Gladia.polls % 2:  # first poll: still processing
            return self.reply(200, {"status": "processing", "result": None})
        langs = req["language_config"]["languages"]
        transcript = "hallo welt" if langs == ["de"] else "error" if langs == ["xx"] else "hello world"
        if transcript == "error":
            return self.reply(200, {"status": "error", "error_code": 500, "result": None})
        return self.reply(200, {"status": "done", "result": {"transcription": {
            "full_transcript": transcript, "utterances": [{"text": transcript, "confidence": 0.8}]}}})


def ws_server(port_holder):
    """Minimal WebSocket server: collects binary frames until stop_recording, then answers."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    port_holder.append(srv.getsockname()[1])

    def recv_exact(conn, n):
        data = b""
        while len(data) < n:
            chunk = conn.recv(n - len(data))
            if not chunk:
                raise EOFError
            data += chunk
        return data

    def frame(payload, opcode=1):
        n = len(payload)
        head = bytes([0x80 | opcode]) + (bytes([n]) if n < 126 else bytes([126]) + struct.pack(">H", n))
        return head + payload

    def handle(conn):
        try:
            request = b""
            while b"\r\n\r\n" not in request:
                request += conn.recv(4096)
            key = [l.split(b":", 1)[1].strip() for l in request.split(b"\r\n") if l.lower().startswith(b"sec-websocket-key")][0]
            accept = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
            conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                         b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n")
            audio = b""
            while True:
                b1, b2 = recv_exact(conn, 2)
                n = b2 & 0x7F
                if n == 126:
                    n = struct.unpack(">H", recv_exact(conn, 2))[0]
                elif n == 127:
                    n = struct.unpack(">Q", recv_exact(conn, 8))[0]
                mask = recv_exact(conn, 4) if b2 & 0x80 else b"\0\0\0\0"
                payload = bytes(c ^ mask[i % 4] for i, c in enumerate(recv_exact(conn, n)))
                opcode = b1 & 0x0F
                if opcode == 2:
                    audio += payload
                elif opcode == 1 and json.loads(payload).get("type") == "stop_recording":
                    Gladia.live_audio.append(audio)
                    for part, conf in (("guten tag", 0.9), ("wie geht's", 0.7)):
                        conn.sendall(frame(json.dumps({"type": "transcript", "data": {"id": part, "is_final": True,
                                     "utterance": {"text": part, "confidence": conf}}}).encode()))
                    conn.sendall(frame(json.dumps({"type": "post_final_transcript", "data": {}}).encode()))
                    conn.sendall(frame(struct.pack(">H", 1000), opcode=8))
                    break
                elif opcode == 8:
                    break
        except Exception:  # noqa: BLE001
            pass
        finally:
            conn.close()

    def loop():
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=handle, args=(conn,), daemon=True).start()
    threading.Thread(target=loop, daemon=True).start()


class WorkerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.exe = os.path.join(cls.dir, "ArmSpeechWorker.exe")
        build_worker(cls.exe, STT_WORKER_SOURCE)
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), MockApi)
        ports = []
        ws_server(ports)
        cls.http.ws_port = ports[0]
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.http.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        Gladia.uploads, Gladia.jobs, Gladia.live_audio, Gladia.polls = [], {}, [], 0
        log = os.path.join(self.dir, "gladia.log")
        if os.path.exists(log):
            os.remove(log)

    def configure(self, **extra):
        config = {"api_key": KEY, "base_url": self.base, "mode": "prerecorded", "timeout_seconds": 10,
                  "poll_interval_ms": 20}
        config.update(extra)
        with open(os.path.join(self.dir, "gladia.json"), "w") as f:
            json.dump(config, f)

    def start(self):
        proc = subprocess.Popen([self.exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.stdin.write(struct.pack("<i", 1))
        proc.stdin.flush()
        self.assertEqual(struct.unpack("<i", proc.stdout.read(4))[0], 1)
        n = struct.unpack("<i", proc.stdout.read(4))[0]
        self.assertEqual(proc.stdout.read(n), b"X64")
        return proc

    def transcribe(self, proc, language, seconds=1.0):
        samples = [0.5 * math.sin(i / 8.0) for i in range(int(16000 * seconds))]
        proc.stdin.write(struct.pack("<i", 1) + text("Moonshine/tiny-streaming-" + language) + text(language) +
                         struct.pack("<i", len(samples)) + struct.pack("<%df" % len(samples), *samples))
        proc.stdin.flush()
        self.assertEqual(struct.unpack("<i", proc.stdout.read(4))[0], 1)
        n = struct.unpack("<i", proc.stdout.read(4))[0]
        result = proc.stdout.read(n).decode("utf-8")
        confidence = struct.unpack("<f", proc.stdout.read(4))[0]
        return result, confidence

    def close(self, proc):
        proc.stdin.close()
        self.assertEqual(proc.wait(10), 0)
        proc.stdout.close()
        proc.stderr.close()

    def log(self):
        with open(os.path.join(self.dir, "gladia.log"), encoding="utf-8") as f:
            return f.read()

    def test_prerecorded_uses_game_language_and_wav(self):
        self.configure()
        proc = self.start()
        self.assertEqual(self.transcribe(proc, "de"), ("hallo welt", 0.800000011920929))
        self.assertEqual(self.transcribe(proc, "en", 2.0)[0], "hello world")
        self.close(proc)
        self.assertEqual(len(Gladia.uploads), 2)
        with wave.open(__import__("io").BytesIO(Gladia.uploads[1])) as w:
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()), (1, 2, 16000, 32000))
        self.assertEqual(Gladia.jobs["0"]["language_config"], {"languages": ["de"], "code_switching": False})
        self.assertIn("ok lang=de", self.log())

    def test_language_override_and_extra_body(self):
        self.configure(language="auto", model="solaria-1", extra_body={"custom_vocabulary": ["Scam"]})
        proc = self.start()
        self.assertEqual(self.transcribe(proc, "de")[0], "hello world")
        self.close(proc)
        job = Gladia.jobs["0"]
        self.assertEqual(job["language_config"]["languages"], [])
        self.assertEqual((job["model"], job["custom_vocabulary"]), ("solaria-1", ["Scam"]))

    def test_errors_become_empty_transcripts(self):
        # A protocol error would turn recognition off for the whole session, so the worker must keep going.
        self.configure(api_key="wrong")
        proc = self.start()
        self.assertEqual(self.transcribe(proc, "de"), ("", 0.0))
        self.close(proc)
        self.assertIn("HTTP 401", self.log())

        self.configure()
        proc = self.start()
        self.assertEqual(self.transcribe(proc, "xx"), ("", 0.0))
        self.assertEqual(self.transcribe(proc, "de")[0], "hallo welt")
        self.close(proc)
        self.assertIn("transcription failed", self.log())

    def test_unreachable_api(self):
        self.configure(base_url="http://127.0.0.1:1", timeout_seconds=3)
        proc = self.start()
        self.assertEqual(self.transcribe(proc, "en"), ("", 0.0))
        self.close(proc)
        self.assertIn("FAILED", self.log())

    def test_live_mode(self):
        self.configure(mode="live")
        proc = self.start()
        result, confidence = self.transcribe(proc, "de", 1.5)
        self.close(proc)
        self.assertEqual(result, "guten tag wie geht's")
        self.assertAlmostEqual(confidence, 0.8, places=5)
        live = Gladia.jobs["live"]
        self.assertEqual((live["encoding"], live["sample_rate"], live["bit_depth"], live["channels"]), ("wav/pcm", 16000, 16, 1))
        self.assertEqual(live["language_config"]["languages"], ["de"])
        self.assertEqual(len(Gladia.live_audio[0]), 2 * 24000)

    def test_key_check(self):
        self.assertEqual(test_key({"api_key": KEY, "base_url": self.base})[0], True)
        ok, message = test_key({"api_key": "nope", "base_url": self.base})
        self.assertFalse(ok)
        self.assertIn("401", message)


SOURCE = os.environ.get("SWYF_GAME_DIR") or next(iter(find_game_dirs()), None)
RUNTIME = "Scam With Your Friends_Data/StreamingAssets/Moonshine/runtime/"
FILES = ("Scam With Your Friends_Data/Managed/ScriptsAssDef.dll", RUNTIME + "ArmSpeechWorker.exe",
         RUNTIME + "runtime-manifest.json")
EXTRA = (RUNTIME + "ArmSpeechNative.dll", RUNTIME + "moonshine-LICENSE.txt")


@unittest.skipUnless(SOURCE, "game not installed")
class SttPatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.worker = os.path.join(cls.tmp, "GladiaSttWorker.exe")
        build_worker(cls.worker, STT_WORKER_SOURCE)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.root = tempfile.mkdtemp(dir=self.tmp)
        for rel in FILES + EXTRA:
            os.makedirs(os.path.dirname(os.path.join(self.root, rel)), exist_ok=True)
            shutil.copy2(os.path.join(SOURCE, rel), os.path.join(self.root, rel))
        self.game = SttGame(self.root)
        self.quiet = lambda line: None

    def test_install_and_restore(self):
        originals = {rel: sha256(os.path.join(self.root, rel)) for rel in FILES}
        self.game.install(SttOptions(), {"api_key": "k"}, self.worker, log=self.quiet)
        self.assertEqual(self.game.status()[0], "patched")
        with open(self.game.dll + ".orig", "rb") as a, open(self.game.dll, "rb") as b:
            before, after = a.read(), b.read()
        self.assertEqual(len(before), len(after))
        self.assertEqual(sum(x != y for x, y in zip(before, after)), 5)
        with open(self.game.manifest, encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual((manifest["protocol"], manifest["architecture"]), (1, "X64"))
        self.assertEqual(manifest["files"]["ArmSpeechWorker.exe"], sha256(self.worker))
        self.assertEqual(set(manifest["files"]), {"ArmSpeechWorker.exe", "ArmSpeechNative.dll", "moonshine-LICENSE.txt"})
        with open(self.game.config, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["api_key"], "k")

        self.game.uninstall(log=self.quiet)
        self.assertEqual({rel: sha256(os.path.join(self.root, rel)) for rel in FILES}, originals)
        self.assertEqual(self.game.status()[0], "original")

    def test_partials_option(self):
        self.game.install(SttOptions(partials=True), {"api_key": "k"}, self.worker, log=self.quiet)
        with open(self.game.dll + ".orig", "rb") as a, open(self.game.dll, "rb") as b:
            self.assertEqual(sum(x != y for x, y in zip(a.read(), b.read())), 4)

    def test_requires_key(self):
        with self.assertRaises(Exception):
            self.game.install(SttOptions(), {"api_key": " "}, self.worker, log=self.quiet)
        self.assertFalse(os.path.exists(self.game.dll + ".orig"))


if __name__ == "__main__":
    unittest.main()
