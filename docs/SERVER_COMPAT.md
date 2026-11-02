# Compatible TTS servers

The remote worker sends every sentence via `POST` to the configured URL. It expects raw
audio back, either WAV or 16-bit PCM, not JSON. So that every character speaks with their
own voice, it can include the character's voice sample. How exactly that sample has to be
sent differs between servers.

> **Status:** November 2026. The ratings are based on each project's documentation. None
> of these servers has been tested against a real instance yet, so always check your
> settings with **Test connection** in the installer or with
> `py patch_qwen.py --test-server`. Reports are welcome.

## Overview

| Server | Voice per character | Game languages | Setup | Rating |
|--------|---------------------|----------------|-------|--------|
| [vLLM-Omni](#vllm-omni) | ✅ automatic (`ref_audio`) | all | [Guide](https://docs.vllm.ai/projects/vllm-omni/en/v0.18.0/user_guide/examples/online_serving/qwen3_tts/) | ✅ recommended, default configuration |
| [Qwen3-TTS-Openai-Fastapi (groxaxo)](#qwen3-tts-openai-fastapi-groxaxo) | ✅ automatic (`/v1/audio/voice-clone`) | all | [Quick start](https://github.com/groxaxo/Qwen3-TTS-Openai-Fastapi#quick-start) | ✅ compatible, also CPU and Docker |
| [qwen3_audio_api (second-state)](#qwen3_audio_api-second-state) | ✅ automatic (`audio_sample`) | all | [Docker quickstart](https://github.com/second-state/qwen3_audio_api) | ✅ compatible |
| [Qwen3-TTS-Openai-Fastapi (dingausmwald)](#qwen3-tts-openai-fastapi-dingausmwald) | 🟡 via saved profiles + `voice_map` | via model name | [Quick Start](https://github.com/dingausmwald/Qwen3-TTS-Openai-Fastapi) | 🟡 limited, good for AMD/ROCm |
| [LocalAI](#localai) | 🟡 via voice profiles + `voice_map` | all | [Qwen3-TTS setup](https://localai.io/docs/features/text-to-audio/) | 🟡 limited |
| [Kokoro-FastAPI](#kokoro-fastapi) | ❌ fixed server voices | no German | [Get Started](https://github.com/remsky/Kokoro-FastAPI#get-started) | ⚪ fixed voices only, very fast |
| [openedai-speech](#openedai-speech) | ❌ only via server configuration | – | [Repo](https://github.com/matatonic/openedai-speech) | ❌ archived, not recommended |

**What "automatic" means:** the server gets the voice sample with every request and clones
the voice itself, just like the game does locally. With 🟡 you register the voices on the
server once and map them with `voice_map`. How to do that is described at the bottom under
[Mapping voices manually](#mapping-voices-manually).

For voice cloning, every Qwen3 server needs a **Base** model, e.g.
`Qwen/Qwen3-TTS-12Hz-0.6B-Base`. The CustomVoice and VoiceDesign models cannot clone.

Where the configuration goes: the blocks below belong in
`…\kolkata-qwen-runtime\qwen-remote.json`. In the installer you set them through the form
fields and *Extra fields*. Fields not listed keep their defaults from
[config/qwen-remote.example.json](../config/qwen-remote.example.json).

---

## vLLM-Omni

An OpenAI-compatible server from the vLLM project. It accepts exactly the request format
the patch sends by default: `ref_audio` as a data URL, `task_type`, `x_vector_only_mode`,
and `language` as a full language name. Requires an NVIDIA GPU.

- **Setup:**
  [Qwen3-TTS Online Serving](https://docs.vllm.ai/projects/vllm-omni/en/v0.18.0/user_guide/examples/online_serving/qwen3_tts/),
  section "Launch the Server". Installing vLLM-Omni itself is covered in its README.
- **Start command from the docs:**
  `vllm serve Qwen/Qwen3-TTS-12Hz-0.6B-Base --omni --port 8091`. Add `--host 0.0.0.0` so
  other machines on the network can connect.
- **Not enough VRAM:** according to the docs, use the 0.6B model or a lower
  `--gpu-memory-utilization`.

```json
{
  "url": "http://SERVER-IP:8091/v1/audio/speech",
  "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
  "response_format": "wav",
  "send_language": true,
  "send_reference_audio": true,
  "reference_audio_field": "ref_audio",
  "reference_audio_encoding": "data_url",
  "extra_body": { "task_type": "Base", "x_vector_only_mode": true }
}
```

## Qwen3-TTS-Openai-Fastapi (groxaxo)

A FastAPI server with Docker images for GPU and CPU (the 0.6B model on CPU). Cloning goes
through a separate endpoint, `/v1/audio/voice-clone`, which expects the voice sample as
**plain base64 without a `data:` prefix**.

- **Setup:**
  [Quick start](https://github.com/groxaxo/Qwen3-TTS-Openai-Fastapi#quick-start).
  GPU: `docker compose up --build qwen3-tts-gpu`. CPU:
  `docker compose --profile cpu up --build qwen3-tts-cpu`.
- **Saved voice profiles (optional):**
  [Voice Library](https://github.com/groxaxo/Qwen3-TTS-Openai-Fastapi/blob/main/docs/voice-library.md).
- The server must run a **Base** checkpoint.
- `x_vector_only_mode` must stay `true`. Otherwise the server requires a transcript
  (`ref_text`), which the game doesn't provide.

```json
{
  "url": "http://SERVER-IP:8880/v1/audio/voice-clone",
  "response_format": "wav",
  "send_language": true,
  "send_reference_audio": true,
  "reference_audio_field": "ref_audio",
  "reference_audio_encoding": "base64",
  "extra_body": { "x_vector_only_mode": true }
}
```

## qwen3_audio_api (second-state)

An OpenAI-compatible server for Qwen3-TTS and Qwen3-ASR, with Dockerfiles for CPU and CUDA.
The voice sample goes into the `audio_sample` field as plain base64. When it is present,
`voice` is ignored and the Base model is used.

- **Setup:** [README](https://github.com/second-state/qwen3_audio_api), section
  "Quickstart with Docker", and the
  [Python variant](https://github.com/second-state/qwen3_audio_api/blob/main/python/README.md).
  The project strongly recommends a CUDA GPU; it is slow on the CPU.

```json
{
  "url": "http://SERVER-IP:8000/v1/audio/speech",
  "response_format": "wav",
  "send_language": true,
  "send_reference_audio": true,
  "reference_audio_field": "audio_sample",
  "reference_audio_encoding": "base64",
  "extra_body": {}
}
```

## Qwen3-TTS-Openai-Fastapi (dingausmwald)

A fork of groxaxo with streaming and optimizations, tested on AMD ROCm. According to its
README it only clones through **saved profiles** (`voice: "clone:Name"`). The language is
chosen through the model name, e.g. `tts-1-en` for English or `tts-1-de` for German. WAV is
not documented, so streamed PCM is used here.

- **Setup:** [README](https://github.com/dingausmwald/Qwen3-TTS-Openai-Fastapi), sections
  "Quick Start" (Docker for NVIDIA/ROCm) and "Manual installation".

```json
{
  "url": "http://SERVER-IP:8880/v1/audio/speech",
  "model": "tts-1-en",
  "voice": "clone:Default",
  "response_format": "pcm",
  "pcm_sample_rate": 24000,
  "send_language": false,
  "send_reference_audio": false,
  "extra_body": { "stream": true },
  "voice_map": { "<hash>": "clone:Jake" }
}
```

## LocalAI

LocalAI is an all-round server for local AI models. Its Qwen3-TTS backend can clone voices,
but only through **voice profiles** on the server. These go into the `voice` field as
`localai://voice-profiles/<uuid>`.

- **Setup:** [Text to Audio](https://localai.io/docs/features/text-to-audio/), section
  "Qwen3-TTS": `local-ai models install qwen-tts`. Create profiles with
  `POST /api/voice-profiles`; the fields are described on the same page.

```json
{
  "url": "http://SERVER-IP:8080/v1/audio/speech",
  "model": "qwen-tts",
  "voice": "localai://voice-profiles/<uuid-of-default-voice>",
  "response_format": "wav",
  "send_language": true,
  "send_reference_audio": false,
  "extra_body": {},
  "voice_map": { "<hash>": "localai://voice-profiles/<uuid>" }
}
```

## Kokoro-FastAPI

A very fast, small TTS server that also runs on the CPU. It only has fixed voices, no voice
cloning and **no German voices**. Useful if you play in English and care more about speed
than about per-character voices.

- **Setup:** [Get Started](https://github.com/remsky/Kokoro-FastAPI#get-started).
  CPU: `docker run -p 8880:8880 ghcr.io/remsky/kokoro-fastapi-cpu:latest`. NVIDIA:
  `docker run --gpus all -p 8880:8880 ghcr.io/remsky/kokoro-fastapi-gpu:latest`.
- Voice names carry a language prefix (`af_…`, `am_…`, `bf_…`). With `voice_map` you can
  give each character its own fixed voice.

```json
{
  "url": "http://SERVER-IP:8880/v1/audio/speech",
  "model": "kokoro",
  "voice": "am_adam",
  "response_format": "pcm",
  "pcm_sample_rate": 24000,
  "send_language": false,
  "send_reference_audio": false,
  "extra_body": {}
}
```

## openedai-speech

The repository has been archived since January 2026; its last release is from 2024. It
would only work with fixed voices from its server configuration
(`send_reference_audio: false`, `extra_body: {}`). **Not recommended.**

---

## Mapping voices manually

For servers that only know voices registered in advance:

1. Leave `dump_references` on (the default) and play through a few calls in the game. The
   worker saves each new voice sample once as
   `…\kolkata-qwen-runtime\remote-voices\<hash>.wav`.
2. `qwen-remote.log` shows which file belongs to which character, e.g.
   `new voice reference 88235bfe873b`. You can also just listen to the WAV files.
3. Register the WAV files on the server as voices or profiles, as described in that
   server's guide.
4. In `qwen-remote.json`, map each hash to its name on the server:
   `"voice_map": { "88235bfe873b": "clone:Jake" }`.
   Characters without an entry get the voice from `voice`.

## Common errors

| Message in the log / connection test | Cause |
|--------------------------------------|-------|
| `HTTP 422` / `HTTP 400` | The server doesn't know a field or expects a different format. Compare *Extra fields* and `reference_audio_encoding` with the matching section above. |
| `missing_ref_text` | `x_vector_only_mode` is not set to `true`. |
| `Server did not return WAV` | The server returns a different format (often mp3). Check `response_format`, or use `pcm` instead. |
| `not reachable` | Wrong IP or port, the firewall is blocking, or the server listens only on `127.0.0.1` instead of `0.0.0.0`. |
