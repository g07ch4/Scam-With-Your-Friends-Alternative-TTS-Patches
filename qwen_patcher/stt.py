"""Patch 3: speech recognition through the Gladia API with the player's own API key.

The game used to offer Gladia as a speech recognition provider; the Steam build removed it. This
patch reuses the game's Moonshine streaming helper instead: the helper is a separate process
(StreamingAssets/Moonshine/runtime/ArmSpeechWorker.exe) with a small stdin/stdout protocol, so it
can be replaced by GladiaSttWorker.exe, which sends each utterance to Gladia.

ScriptsAssDef.dll changes (all same-length IL edits):
  * WindowsSpeechCompatibility.get_PreferMoonshine -> always true (Whisper is never used)
  * MoonshineStreamingRuntime.SupportsLanguage      -> always true (the helper handles every language)
  * WhisperVcPipeline.QueueInference                 -> returns early for partial (non-final) requests,
    so each utterance is sent to Gladia once instead of every partialIntervalSeconds (optional).
"""
import json
import os
import re
import shutil
import struct

from .core import PatchError, build_worker, sha256
from .paths import BUNDLED_STT_WORKER, STT_WORKER_SOURCE

# get_PreferMoonshine: call IsWindowsArm64 ; brtrue IL_008C ; ldsfld whisperFailed ; brtrue.s IL_008A ;
#                      call get_RecognitionPreference ; ldstr "Moonshine" ; call op_Equality ; brtrue.s
PREFER_RE = re.compile(rb"\x28....\x3A\x82\x00\x00\x00\x7E....\x2D\x79\x28....\x72....\x28....\x2D\x68", re.S)
# SupportsLanguage: lang == "ar" || "de" || "ja" || "zh" || lang == "es"
SUPPORTS_RE = re.compile(rb"\x02\x72(....)\x28....\x2D\x33\x02\x72(....)\x28....\x2D\x26\x02\x72(....)\x28....\x2D\x19"
                         rb"\x02\x72(....)\x28....\x2D\x0C\x02\x72(....)\x28....\x2A\x17\x2A", re.S)
SUPPORTS_LANGUAGES = ("ar", "de", "ja", "zh", "es")
# QueueInference: if (IsWindowsArm64 && armWorkerFailed) return; if (!isFinal && (inferenceInProgress || ...)) return;
#   ... ldarg.2 ; brtrue.s IL_0029 ; [ldarg.0] ldfld inferenceInProgress ; brtrue.s ; call realtime ; ldarg.0 ; ldfld ; bge.un.s ; ret
PARTIAL_RE = re.compile(rb"\x28....\x2C\x09\x02\x7B....\x2C\x01\x2A\x04\x2D\x16(\x02)\x7B....\x2D\x0D\x28....\x02\x7B....\x34\x01\x2A",
                        re.S)

# Validate() requires these two entries and checks their PE machine type (x64).
MANIFEST_FILES = ("ArmSpeechWorker.exe", "ArmSpeechNative.dll", "moonshine-LICENSE.txt")


class SttOptions(object):
    def __init__(self, partials=False):
        self.partials = bool(partials)

    def to_dict(self):
        return dict(vars(self))


def _user_string(data, token):
    """Resolve an ldstr token through the #US heap of a .NET assembly."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    optsz = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    dirs = opt + (96 if struct.unpack_from("<H", data, opt)[0] == 0x10B else 112)
    sections = [struct.unpack_from("<IIII", data, pe + 24 + optsz + 40 * i + 8) for i in range(nsec)]

    def offset(rva):
        for vsize, va, rsize, raw in sections:
            if va <= rva < va + max(vsize, rsize):
                return rva - va + raw
        raise PatchError("Invalid assembly layout.")

    cli = offset(struct.unpack_from("<I", data, dirs + 14 * 8)[0])
    root = offset(struct.unpack_from("<I", data, cli + 8)[0])
    p = root + 16 + struct.unpack_from("<I", data, root + 12)[0] + 2
    count = struct.unpack_from("<H", data, p)[0]
    p += 2
    heap = None
    for _ in range(count):
        off, _size = struct.unpack_from("<II", data, p)
        end = data.index(b"\0", p + 8)
        name = data[p + 8:end]
        p = (end + 4) & ~3
        if name == b"#US":
            heap = root + off
    if heap is None or token >> 24 != 0x70:
        return None
    q = heap + (token & 0xFFFFFF)
    b = data[q]
    if b & 0x80 == 0:
        n, q = b, q + 1
    elif b & 0xC0 == 0x80:
        n, q = ((b & 0x3F) << 8) | data[q + 1], q + 2
    else:
        n, q = ((b & 0x1F) << 24) | (data[q + 1] << 16) | (data[q + 2] << 8) | data[q + 3], q + 4
    return data[q:q + n - 1].decode("utf-16-le", "replace")


def _one(regex, data, what):
    matches = list(regex.finditer(data))
    if len(matches) != 1:
        raise PatchError("%s not found unambiguously - unsupported game version." % what)
    return matches[0]


def patch_scripts_dll(data, options, log=print):
    raw = bytes(data)
    data = bytearray(data)

    at = _one(PREFER_RE, raw, "WindowsSpeechCompatibility.PreferMoonshine").start()
    data[at:at + 2] = b"\x17\x2A"  # ldc.i4.1 ; ret

    supports = [m for m in SUPPORTS_RE.finditer(raw)
                if tuple(_user_string(raw, struct.unpack("<I", m.group(i))[0]) for i in range(1, 6)) == SUPPORTS_LANGUAGES]
    if len(supports) != 1:
        raise PatchError("MoonshineStreamingRuntime.SupportsLanguage not found - unsupported game version.")
    at = supports[0].start()
    data[at:at + 2] = b"\x17\x2A"  # ldc.i4.1 ; ret

    if not options.partials:
        at = _one(PARTIAL_RE, raw, "WhisperVcPipeline.QueueInference").start(1)
        data[at] = 0x2A  # ldarg.0 -> ret: partial (non-final) requests are dropped
    log("Speech recognition routed to the Gladia helper%s" % ("" if options.partials else ", partial transcripts off"))
    return bytes(data)


def stt_manifest(text, runtime_dir):
    manifest = json.loads(text)
    manifest["files"] = {name: sha256(os.path.join(runtime_dir, name)) for name in MANIFEST_FILES}
    return json.dumps(manifest, indent=2) + "\n"


class SttGame(object):
    def __init__(self, root):
        data = os.path.join(root, "Scam With Your Friends_Data")
        self.root = root
        self.dll = os.path.join(data, "Managed", "ScriptsAssDef.dll")
        self.runtime = os.path.join(data, "StreamingAssets", "Moonshine", "runtime")
        self.worker = os.path.join(self.runtime, "ArmSpeechWorker.exe")
        self.manifest = os.path.join(self.runtime, "runtime-manifest.json")
        self.config = os.path.join(self.runtime, "gladia.json")
        self.log_file = os.path.join(self.runtime, "gladia.log")
        self.state_file = os.path.join(self.runtime, "gladia-patch-state.json")
        for path in (self.dll, self.worker, self.manifest):
            if not os.path.isfile(path):
                raise PatchError("Missing game file: %s" % path)

    @property
    def files(self):
        return (self.dll, self.worker, self.manifest)

    def state(self):
        try:
            with open(self.state_file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def status(self):
        state = self.state()
        patched = state.get("patched")
        if not patched:
            return "original", None
        if all(sha256(p) == patched.get(os.path.basename(p)) for p in self.files):
            return "patched", state.get("options")
        return "reverted", state.get("options")

    def _original(self, path, state):
        backup = path + ".orig"
        current = sha256(path)
        patched = state.get("patched", {}).get(os.path.basename(path))
        if not os.path.exists(backup) or (current != patched and current != sha256(backup)):
            shutil.copy2(path, backup)
        return backup

    def install(self, options, config=None, worker_exe=None, log=print):
        worker_exe = worker_exe or BUNDLED_STT_WORKER
        if not os.path.isfile(worker_exe):
            log("Building GladiaSttWorker.exe ...")
            build_worker(worker_exe, STT_WORKER_SOURCE)
        if config is None and not os.path.isfile(self.config):
            raise PatchError("Gladia needs a configuration with your API key.")
        if config is not None and not str(config.get("api_key", "")).strip():
            raise PatchError("Please enter your Gladia API key.")
        for name in MANIFEST_FILES[1:]:
            if not os.path.isfile(os.path.join(self.runtime, name)):
                raise PatchError("Missing game file: %s" % os.path.join(self.runtime, name))

        state = self.state()
        for path in self.files:
            self._original(path, state)
        with open(self.dll + ".orig", "rb") as f:
            dll = patch_scripts_dll(f.read(), options, log)
        with open(self.manifest + ".orig", encoding="utf-8", newline="") as f:
            manifest = f.read()

        with open(self.dll, "wb") as f:
            f.write(dll)
        shutil.copy2(worker_exe, self.worker)
        with open(self.manifest, "w", encoding="utf-8", newline="") as f:
            f.write(stt_manifest(manifest, self.runtime))
        if config is not None:
            with open(self.config, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
                f.write("\n")

        state["patched"] = {os.path.basename(p): sha256(p) for p in self.files}
        state["options"] = options.to_dict()
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        log("Gladia speech recognition installed. Restart the game if it is running.")

    def uninstall(self, log=print):
        restored = False
        for path in self.files:
            backup = path + ".orig"
            if os.path.exists(backup):
                shutil.copy2(backup, path)
                os.remove(backup)
                restored = True
                log("Restored %s" % os.path.relpath(path, self.root))
        if os.path.exists(self.state_file):
            os.remove(self.state_file)
        log("Original speech recognition restored." if restored else "Speech recognition: nothing to restore.")


def test_key(config, timeout=15):
    """Checks the API key by uploading 0.5 s of silence (uploads are not transcribed or billed as audio)."""
    import io
    import urllib.request
    import uuid
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0\0" * 8000)
    boundary = "----swyf" + uuid.uuid4().hex
    body = (("--%s\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"test.wav\"\r\n"
             "Content-Type: audio/wav\r\n\r\n" % boundary).encode() + buf.getvalue() + ("\r\n--%s--\r\n" % boundary).encode())
    base = (config.get("base_url") or "https://api.gladia.io").rstrip("/")
    req = urllib.request.Request(base + "/v2/upload", data=body, method="POST", headers={
        "x-gladia-key": str(config.get("api_key", "")).strip(),
        "Content-Type": "multipart/form-data; boundary=" + boundary, "Accept": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            answer = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        if e.code == 401:
            return False, "API key rejected (HTTP 401)."
        return False, "HTTP %d: %s" % (e.code, detail)
    except Exception as e:  # noqa: BLE001
        return False, "Gladia not reachable: %s" % e
    if not answer.get("audio_url"):
        return False, "Unexpected answer: %s" % str(answer)[:200]
    return True, "API key works."
