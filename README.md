# Qwen3 TTS patch for *Scam With Your Friends*

An unofficial community patch for the game's Qwen3 voice synthesis. It has two parts,
which you can install on their own or together:

| Patch | What it does |
|-------|--------------|
| **1 – Lower the hardware requirements** | Qwen3 TTS also runs on weaker PCs: less VRAM and RAM, and optionally no suitable GPU at all. |
| **2 – Offload TTS to a server** | Speech is synthesized on a machine in your local network that offers the OpenAI speech API (`POST /v1/audio/speech`). The gaming PC then needs neither a GPU for Qwen nor the 2 GB model download. |

The patch ships **no game files**. It modifies the installed files on the player's machine
and backs them up first. It only works on Windows with the Steam version of the game
(app ID 4954910).

---

## Installation (recommended: graphical installer)

**Requirement:** [Python 3](https://www.python.org/downloads/) with the default options
(tkinter is included).

1. Download the latest release ZIP and extract it anywhere. It does not have to be inside
   the game folder.
2. Double-click **`install.cmd`**.
3. The installer finds the game through Steam. If it doesn't, click **Browse…** and select
   the folder `…\steamapps\common\Scam With Your Friends`.
4. Choose the patches:
   - **Patch 1:** adjust the minimum values or keep the defaults.
   - **Patch 2:** enter the server URL, e.g. `http://192.168.1.50:8000/v1/audio/speech`,
     then click **Test connection**.
5. Click **Install**.
6. In the game's voice settings, **prioritize "Qwen3 TTS"**.

To remove the patch, click **Uninstall** in the installer. This restores the original files
bit for bit.

### Command line

```bash
py patch_qwen.py --lowreq
```

```bash
py patch_qwen.py --lowreq --vram 2048 --ram 6000 --allow-cpu
```

```bash
py patch_qwen.py --remote --url http://192.168.1.50:8000/v1/audio/speech
```

```bash
py patch_qwen.py --test-server
```

```bash
py patch_qwen.py --status
```

```bash
py patch_qwen.py --restore
```

Use `--game-dir "D:\Steam\steamapps\common\Scam With Your Friends"` to set the game folder,
and `--config my-server.json` to use your own server configuration.

### Without Python (manual)

Instructions using a hex editor: **[docs/MANUAL_INSTALL.md](docs/MANUAL_INSTALL.md)**.

---

## After a game update

A game update or Steam's "Verify integrity of game files" replaces the patched files with
the originals. The installer then shows *"Patch was removed by a game update"*. Just click
**Install** again: the patcher backs up the new originals and patches them.

If an update changes the affected code, the patcher stops with *"unsupported game
version"* and leaves every file untouched. In that case a new version of the patch is
needed.

---

## Patch 1 in detail

The game checks the following in `QwenWorkerClient.HardwareEligible`:

| Check | Original | Patch default |
|-------|---------:|--------------:|
| VRAM | 5632 MiB | 3072 MiB |
| System RAM | 15000 MiB | 7000 MiB |
| Free RAM | 8192 MiB | 3072 MiB |
| CPU threads | 4 | 2 |
| NVIDIA or AMD GPU required | yes | yes (can be turned off with "allow CPU") |

Good to know:

- **On the CPU without a GPU**, Qwen is usually too slow. If no audio arrives within 20 s,
  the game automatically switches back to its regular voice.
- The game's list of individually blocked graphics cards stays unchanged, and so does the
  8 GB memory limit for the worker process.
- Values that are too low can crash the Qwen worker (not the game). The game then uses its
  regular voice for the rest of the session.

## Patch 2 in detail

```
Game ──stdin/stdout──▶ QwenTtsWorker.exe (proxy) ──HTTP──▶ TTS server on your network
      (text + voice sample)                        POST /v1/audio/speech
```

- The original `QwenTtsWorker.exe` is replaced by a proxy that speaks the same protocol.
  The checksum in `runtime-manifest.json` is updated to match.
- The hardware check always reports "eligible", and the model download is skipped.
- If the server is unreachable or returns an error, the game simply uses its regular voice.

### Request sent to the server

```json
{
  "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
  "input": "Hello, this is your bank calling.",
  "voice": "default",
  "response_format": "wav",
  "language": "English",
  "ref_audio": "data:audio/wav;base64,UklGR…",
  "task_type": "Base",
  "x_vector_only_mode": true
}
```

- `ref_audio` is the character's voice sample (24 kHz mono, at most 10 s). This way every
  character speaks with their own voice, just like with local Qwen.
- WAV responses are accepted with any sample rate and channel count, at 8/16/24/32 bit or
  float. Alternatively use `pcm` (raw 16 bit), which starts playing while it downloads.

### Which server?

The list of compatible servers is in **[docs/SERVER_COMPAT.md](docs/SERVER_COMPAT.md)**. For
each server it links the setup guide and gives a ready-made configuration.

| Server | Voice per character | Rating |
|--------|---------------------|--------|
| vLLM-Omni | ✅ automatic | recommended, default configuration |
| Qwen3-TTS-Openai-Fastapi (groxaxo) | ✅ automatic | compatible, also CPU/Docker |
| qwen3_audio_api (second-state) | ✅ automatic | compatible |
| Qwen3-TTS-Openai-Fastapi (dingausmwald), LocalAI | 🟡 via profiles + `voice_map` | limited |
| Kokoro-FastAPI | ❌ fixed voices, no German | fixed voices only |
| openedai-speech | ❌ | archived |

The ratings are based on each project's documentation; none of them has been tested
against a real server yet. Use **Test connection** in the installer to check your server
right away.

### Configuration

The installer writes
`Scam With Your Friends_Data\StreamingAssets\kolkata-qwen-runtime\qwen-remote.json`.
Template: [config/qwen-remote.example.json](config/qwen-remote.example.json).

| Field | Meaning |
|-------|---------|
| `url` | Full endpoint URL. The `QWEN_REMOTE_URL` environment variable overrides it. |
| `api_key` | Sent as `Authorization: Bearer …` when set. |
| `model`, `voice` | Passed to the server unchanged. |
| `response_format` | `wav` or `pcm`. For `pcm`, `pcm_sample_rate` sets the rate (default 24000). |
| `timeout_seconds` | HTTP timeout. The game itself gives up after 20 s without audio. |
| `send_language` | Sends the language as `language` (`English`, `German`, …). |
| `send_reference_audio` | Sends the character's voice sample. |
| `reference_audio_field` | Field name for the voice sample (default `ref_audio`). |
| `reference_audio_encoding` | `data_url` (`data:audio/wav;base64,…`, default) or `base64` (plain base64). |
| `extra_body` | Merged into every request as is. |
| `voice_map` | Maps voice-sample hashes to server voices, e.g. `{"88235bfe873b": "jake"}`. |
| `dump_references` | Saves each voice sample once as `remote-voices\<hash>.wav`. You can register these files on the server as fixed voices and map them with `voice_map`. |

You can edit the file directly. Changes take effect the next time the game loads Qwen; no
need to patch again. **Open runtime folder** in the installer takes you to the
configuration, the log `qwen-remote.log` and `remote-voices`.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| The game keeps using its regular voice | Is "Qwen3 TTS" prioritized in the voice settings? Does the installer show the status "Patched"? |
| `qwen-remote.log`: *not reachable* | Check the server IP and port, open the firewall on the server, and make the server listen on `0.0.0.0`. |
| `HTTP 400/422` | The server doesn't know a field. Set *Extra fields* to `{}` or turn off "Send voice sample". |
| Speech arrives late or cuts off | The server is too slow (limit: 20 s until the first audio). Use a smaller model or `pcm`. |
| *unsupported game version* | The game update changed the code. Wait for a new patch version. |
| Unity log | `%USERPROFILE%\AppData\LocalLow\Jatater Worldwide\Scam With Your Friends\Player.log`, entries tagged `[Qwen3 TTS]`. |

---

## Development

```
qwen_patcher/   patch logic (core.py), server test (remote.py)
installer.pyw   graphical installer (tkinter)
patch_qwen.py   command line
worker/         source of the remote worker (C# 5, builds with Windows' own csc.exe)
tests/          worker against a mock server; patcher against a copy of the real game files
tools/          builds the release ZIP
docs/           manual installation, server compatibility, technical details
```

```bash
py -m unittest discover -s tests -v
```

```bash
py tools/build_release.py
```

The patcher tests need an installed copy of the game (found through Steam or set with
`SWYF_GAME_DIR`) and only work on copies of its files. Technical background is in
[docs/TECHNICAL.md](docs/TECHNICAL.md).

## Disclaimer

Unofficial fan project, not affiliated with the game's developers. Use at your own risk.
Let everyone know before playing online with friends; the patch only changes the local
voice output.
