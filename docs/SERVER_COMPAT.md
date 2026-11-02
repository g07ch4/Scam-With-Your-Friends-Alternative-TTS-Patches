# Kompatible TTS-Server

Der Remote-Worker schickt jeden Satz per `POST` an die eingestellte URL. Zurück erwartet
er rohe Audiodaten, also WAV oder 16-Bit-PCM, kein JSON. Damit jede Spielfigur mit ihrer
eigenen Stimme spricht, kann er die Stimmprobe der Figur mitsenden. Wie das genau
aussieht, unterscheidet sich je nach Server.

> **Stand:** November 2026. Die Einstufung beruht auf der Dokumentation der Projekte.
> Gegen einen echten Server habe ich bisher keinen davon getestet. Prüfe die
> Einstellungen deshalb immer mit **„Verbindung testen“** im Installer bzw. mit
> `py patch_qwen.py --test-server`. Rückmeldungen nehme ich gern auf.

## Übersicht

| Server | Stimme pro Figur | Spiel-Sprachen | Einrichtung | Bewertung |
|--------|------------------|----------------|-------------|-----------|
| [vLLM-Omni](#vllm-omni) | ✅ automatisch (`ref_audio`) | alle | [Anleitung](https://docs.vllm.ai/projects/vllm-omni/en/v0.18.0/user_guide/examples/online_serving/qwen3_tts/) | ✅ empfohlen, Standard-Konfiguration |
| [Qwen3-TTS-Openai-Fastapi (groxaxo)](#qwen3-tts-openai-fastapi-groxaxo) | ✅ automatisch (`/v1/audio/voice-clone`) | alle | [Quick start](https://github.com/groxaxo/Qwen3-TTS-Openai-Fastapi#quick-start) | ✅ kompatibel, auch CPU und Docker |
| [qwen3_audio_api (second-state)](#qwen3_audio_api-second-state) | ✅ automatisch (`audio_sample`) | alle | [Docker-Quickstart](https://github.com/second-state/qwen3_audio_api) | ✅ kompatibel |
| [Qwen3-TTS-Openai-Fastapi (dingausmwald)](#qwen3-tts-openai-fastapi-dingausmwald) | 🟡 über angelegte Profile + `voice_map` | über Modellnamen | [Quick Start](https://github.com/dingausmwald/Qwen3-TTS-Openai-Fastapi) | 🟡 eingeschränkt, gut für AMD/ROCm |
| [LocalAI](#localai) | 🟡 über Voice-Profile + `voice_map` | alle | [Qwen3-TTS-Setup](https://localai.io/docs/features/text-to-audio/) | 🟡 eingeschränkt |
| [Kokoro-FastAPI](#kokoro-fastapi) | ❌ feste Server-Stimmen | kein Deutsch | [Get Started](https://github.com/remsky/Kokoro-FastAPI#get-started) | ⚪ nur feste Stimmen, sehr schnell |
| [openedai-speech](#openedai-speech) | ❌ nur per Server-Konfiguration | – | [Repo](https://github.com/matatonic/openedai-speech) | ❌ archiviert, nicht empfohlen |

**Was „automatisch“ bedeutet:** Der Server bekommt die Stimmprobe mit jedem Request und
klont die Stimme selbst, genau wie das Spiel es lokal macht. Bei 🟡 legst du die Stimmen
einmal auf dem Server an und ordnest sie über `voice_map` zu. Wie das geht, steht ganz
unten unter [Stimmen manuell zuordnen](#stimmen-manuell-zuordnen).

Für das Voice-Cloning brauchen alle Qwen3-Server ein **Base**-Modell, z. B.
`Qwen/Qwen3-TTS-12Hz-0.6B-Base`. Die CustomVoice- und VoiceDesign-Modelle können nicht
klonen.

Wo die Konfiguration steht: Die Blöcke unten gehören in
`…\kolkata-qwen-runtime\qwen-remote.json`. Im Installer setzt du sie über die Felder und
*Zusätzliche Felder*. Nicht aufgeführte Felder behalten ihren Standardwert aus
[config/qwen-remote.example.json](../config/qwen-remote.example.json).

---

## vLLM-Omni

Ein OpenAI-kompatibler Server des vLLM-Projekts. Er nimmt genau das Request-Format an, das
der Patch standardmäßig sendet: `ref_audio` als Data-URL, `task_type`,
`x_vector_only_mode` und `language` mit vollem Sprachnamen. Braucht eine NVIDIA-GPU.

- **Einrichtung:**
  [Qwen3-TTS Online Serving](https://docs.vllm.ai/projects/vllm-omni/en/v0.18.0/user_guide/examples/online_serving/qwen3_tts/),
  Abschnitt „Launch the Server“. Die Installation von vLLM-Omni beschreibt dessen README.
- **Startbefehl laut Doku:**
  `vllm serve Qwen/Qwen3-TTS-12Hz-0.6B-Base --omni --port 8091`. Damit andere Rechner im
  Netz zugreifen können, zusätzlich `--host 0.0.0.0`.
- **Zu wenig VRAM:** Laut Doku hilft das 0.6B-Modell oder ein niedrigeres
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

Ein FastAPI-Server mit Docker-Images für GPU und CPU (auf der CPU das 0.6B-Modell).
Geklont wird über einen eigenen Endpoint `/v1/audio/voice-clone`. Der erwartet die
Stimmprobe als **rohes Base64 ohne `data:`-Präfix**.

- **Einrichtung:**
  [Quick start](https://github.com/groxaxo/Qwen3-TTS-Openai-Fastapi#quick-start).
  GPU per `docker compose up --build qwen3-tts-gpu`, CPU per
  `docker compose --profile cpu up --build qwen3-tts-cpu`.
- **Gespeicherte Stimmprofile (optional):**
  [Voice Library](https://github.com/groxaxo/Qwen3-TTS-Openai-Fastapi/blob/main/docs/voice-library.md).
- Der Server muss mit einem **Base**-Checkpoint laufen.
- `x_vector_only_mode` muss `true` bleiben. Sonst verlangt der Server ein Transkript
  (`ref_text`), und das liefert das Spiel nicht.

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

Ein OpenAI-kompatibler Server für Qwen3-TTS und Qwen3-ASR, mit Dockerfiles für CPU und
CUDA. Die Stimmprobe kommt als rohes Base64 ins Feld `audio_sample`. Ist sie dabei, wird
`voice` ignoriert und das Base-Modell genutzt.

- **Einrichtung:** [README](https://github.com/second-state/qwen3_audio_api), Abschnitt
  „Quickstart with Docker“, und die
  [Python-Variante](https://github.com/second-state/qwen3_audio_api/blob/main/python/README.md).
  Die Projektseite empfiehlt dringend eine CUDA-GPU; auf der CPU ist es langsam.

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

Ein Fork von groxaxo mit Streaming und Optimierungen, getestet unter AMD ROCm. Laut README
klont er nur über **gespeicherte Profile** (`voice: "clone:Name"`). Die Sprache wird über
den Modellnamen gewählt, z. B. `tts-1-de`. WAV ist nicht dokumentiert, deshalb wird hier
gestreamtes PCM verwendet.

- **Einrichtung:** [README](https://github.com/dingausmwald/Qwen3-TTS-Openai-Fastapi),
  Abschnitte „Quick Start“ (Docker für NVIDIA/ROCm) und „Manual installation“.

```json
{
  "url": "http://SERVER-IP:8880/v1/audio/speech",
  "model": "tts-1-de",
  "voice": "clone:Standard",
  "response_format": "pcm",
  "pcm_sample_rate": 24000,
  "send_language": false,
  "send_reference_audio": false,
  "extra_body": { "stream": true },
  "voice_map": { "<hash>": "clone:Jake" }
}
```

## LocalAI

LocalAI ist ein Allround-Server für lokale KI-Modelle. Der Qwen3-TTS-Backend kann Stimmen
klonen, allerdings nur über **Voice-Profile** auf dem Server. Diese werden im Feld `voice`
als `localai://voice-profiles/<uuid>` angegeben.

- **Einrichtung:** [Text to Audio](https://localai.io/docs/features/text-to-audio/),
  Abschnitt „Qwen3-TTS“: `local-ai models install qwen-tts`. Profile legst du per
  `POST /api/voice-profiles` an; die Felder dafür stehen auf derselben Seite.

```json
{
  "url": "http://SERVER-IP:8080/v1/audio/speech",
  "model": "qwen-tts",
  "voice": "localai://voice-profiles/<uuid-Standardstimme>",
  "response_format": "wav",
  "send_language": true,
  "send_reference_audio": false,
  "extra_body": {},
  "voice_map": { "<hash>": "localai://voice-profiles/<uuid>" }
}
```

## Kokoro-FastAPI

Ein sehr schneller, kleiner TTS-Server, der auch auf der CPU läuft. Er hat aber nur feste
Stimmen, kein Voice-Cloning und **keine deutschen Stimmen**. Sinnvoll, wenn du auf
Englisch spielst und Geschwindigkeit wichtiger ist als Figuren-Stimmen.

- **Einrichtung:** [Get Started](https://github.com/remsky/Kokoro-FastAPI#get-started).
  CPU: `docker run -p 8880:8880 ghcr.io/remsky/kokoro-fastapi-cpu:latest`. NVIDIA:
  `docker run --gpus all -p 8880:8880 ghcr.io/remsky/kokoro-fastapi-gpu:latest`.
- Die Stimmnamen tragen ein Sprachpräfix (`af_…`, `am_…`, `bf_…`). Über `voice_map`
  kannst du jeder Figur eine eigene feste Stimme geben.

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

Das Repository ist seit Januar 2026 archiviert; die letzte Version stammt von 2024.
Funktionieren würde es nur mit festen Stimmen aus der Server-Konfiguration
(`send_reference_audio: false`, `extra_body: {}`). **Nicht empfohlen.**

---

## Stimmen manuell zuordnen

Für Server, die nur vorher angelegte Stimmen kennen:

1. `dump_references` eingeschaltet lassen (Standard) und im Spiel ein paar Anrufe
   durchspielen. Der Worker speichert jede neue Stimmprobe einmal als
   `…\kolkata-qwen-runtime\remote-voices\<hash>.wav`.
2. Welche Datei zu welcher Figur gehört, zeigt `qwen-remote.log`, z. B.
   `new voice reference 88235bfe873b`. Du kannst die WAV-Dateien auch einfach anhören.
3. Die WAV-Dateien auf dem Server als Stimme oder Profil anlegen. Wie das geht, steht in
   der Anleitung des jeweiligen Servers.
4. In `qwen-remote.json` jedem Hash den Namen auf dem Server zuordnen:
   `"voice_map": { "88235bfe873b": "clone:Jake" }`.
   Figuren ohne Eintrag bekommen die Stimme aus `voice`.

## Häufige Fehler

| Meldung im Log / beim Test | Ursache |
|----------------------------|---------|
| `HTTP 422` / `HTTP 400` | Der Server kennt ein Feld nicht oder erwartet ein anderes Format. *Zusätzliche Felder* und `reference_audio_encoding` mit dem passenden Abschnitt oben vergleichen. |
| `missing_ref_text` | `x_vector_only_mode` steht nicht auf `true`. |
| `Server did not return WAV` | Der Server liefert ein anderes Format (oft mp3). `response_format` prüfen, alternativ `pcm` verwenden. |
| `not reachable` | IP oder Port falsch, die Firewall blockiert, oder der Server lauscht nur auf `127.0.0.1` statt `0.0.0.0`. |
