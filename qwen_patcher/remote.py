"""Connection test for the TTS server - sends the same request the in-game worker sends."""
import base64
import io
import json
import math
import struct
import time
import urllib.error
import urllib.request
import wave


def _reference_wav(seconds=2.0, rate=24000):
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(rate)
    w.writeframes(b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * 180 * i / rate)))
                           for i in range(int(seconds * rate))))
    w.close()
    return buf.getvalue()


def build_request(config, text, language="English"):
    body = {
        "model": config.get("model", "tts-1"),
        "input": text,
        "voice": config.get("voice", "default"),
        "response_format": config.get("response_format", "wav"),
    }
    if config.get("send_language", True):
        body["language"] = language
    if config.get("send_reference_audio", False):
        wav = base64.b64encode(_reference_wav()).decode()
        body[config.get("reference_audio_field", "ref_audio")] = \
            wav if config.get("reference_audio_encoding") == "base64" else "data:audio/wav;base64," + wav
    body.update(config.get("extra_body") or {})
    return body


def test_server(config, text="This is a connection test.", language="English"):
    """Returns a human readable result line; raises on failure."""
    url = config.get("url")
    if not url:
        raise ValueError("No server URL configured.")
    body = json.dumps(build_request(config, text, language)).encode()
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    if config.get("api_key"):
        request.add_header("Authorization", "Bearer " + config["api_key"])
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started = time.time()
    try:
        with opener.open(request, timeout=int(config.get("timeout_seconds", 25))) as response:
            audio = response.read()
            kind = response.headers.get("Content-Type", "?")
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        raise IOError("HTTP %d: %s" % (e.code, detail))
    took = time.time() - started
    if not audio:
        raise IOError("Server returned no audio.")
    fmt = config.get("response_format", "wav")
    if fmt == "wav":
        if audio[:4] != b"RIFF":
            raise IOError("Server did not return WAV (Content-Type %s). Check response_format." % kind)
        with wave.open(io.BytesIO(audio)) as w:
            seconds = w.getnframes() / float(w.getframerate()) if w.getnframes() else 0
            info = "%d Hz, %d ch, %.1f s" % (w.getframerate(), w.getnchannels(), seconds)
    else:
        info = "%.1f s PCM" % (len(audio) / 2.0 / int(config.get("pcm_sample_rate", 24000)))
    return "OK: %d bytes audio (%s) in %.2f s" % (len(audio), info, took)
