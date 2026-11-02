# Qwen3-TTS-Patch für *Scam With Your Friends*

Inoffizieller Community-Patch für die Qwen3-Sprachausgabe des Spiels. Er besteht aus zwei
Teilen, die du einzeln oder zusammen installieren kannst:

| Patch | Was er macht |
|-------|--------------|
| **1 – Hardware-Anforderungen senken** | Qwen3 TTS läuft auch auf schwächeren PCs (weniger VRAM und RAM, optional ganz ohne passende GPU). |
| **2 – TTS auf einen Server auslagern** | Die Sprachsynthese läuft auf einem Rechner im Heimnetz, der die OpenAI-Speech-API (`POST /v1/audio/speech`) anbietet. Auf dem Spiele-PC braucht Qwen dann weder GPU noch den 2-GB-Modell-Download. |

Der Patch enthält **keine Spieldateien**. Er ändert die installierten Dateien beim Spieler
direkt und legt vorher Backups an. Er funktioniert nur unter Windows mit der
Steam-Version (App-ID 4954910).

---

## Installation (empfohlen: grafischer Installer)

**Voraussetzung:** [Python 3](https://www.python.org/downloads/), Standardinstallation
(tkinter ist dann schon dabei).

1. Neuestes Release-ZIP herunterladen und an einem beliebigen Ort entpacken (es muss nicht
   im Spielordner liegen).
2. **`install.cmd`** doppelklicken.
3. Der Installer findet das Spiel über Steam. Falls nicht: **Durchsuchen…** und den Ordner
   `…\steamapps\common\Scam With Your Friends` auswählen.
4. Patches auswählen:
   - **Patch 1:** Mindestwerte anpassen oder die Vorgaben übernehmen.
   - **Patch 2:** Server-URL eintragen, z. B. `http://192.168.1.50:8000/v1/audio/speech`,
     dann **Verbindung testen**.
5. **Installieren** klicken.
6. Im Spiel in den Spracheinstellungen **„Qwen3 TTS“ priorisieren**.

Zum Entfernen im Installer auf **Deinstallieren** klicken. Das stellt die Originaldateien
bit-identisch wieder her.

### Kommandozeile

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

Mit `--game-dir "D:\Steam\steamapps\common\Scam With Your Friends"` gibst du den
Spielordner vor, mit `--config eigene.json` eine eigene Server-Konfiguration.

### Ohne Python (manuell)

Anleitung mit Hex-Editor: **[docs/MANUAL_INSTALL.md](docs/MANUAL_INSTALL.md)**.

---

## Nach einem Spiel-Update

Ein Spiel-Update oder Steam „Dateien auf Fehler überprüfen“ ersetzt die gepatchten Dateien
durch die Originale. Der Installer zeigt dann *„Patch wurde durch ein Spiel-Update
entfernt“* an. Einfach noch einmal **Installieren** klicken: Der Patcher übernimmt die
neuen Originale als Backup und patcht sie.

Ändert ein Update den betroffenen Code, bricht der Patcher mit *„unsupported game
version“* ab und lässt alle Dateien unverändert. Dann wird eine neue Version des Patches
gebraucht.

---

## Patch 1 im Detail

Das Spiel prüft in `QwenWorkerClient.HardwareEligible`:

| Prüfung | Original | Patch-Standard |
|---------|---------:|---------------:|
| VRAM | 5632 MiB | 3072 MiB |
| System-RAM | 15000 MiB | 7000 MiB |
| Freier RAM | 8192 MiB | 3072 MiB |
| CPU-Threads | 4 | 2 |
| NVIDIA- oder AMD-GPU nötig | ja | ja (abschaltbar mit „CPU erlauben“) |

Gut zu wissen:

- **Ohne GPU auf der CPU** ist Qwen meist zu langsam. Kommt nach 20 s noch kein Audio,
  wechselt das Spiel automatisch zurück auf die normale Stimme.
- Die Liste einzelner gesperrter Grafikkarten im Spiel bleibt unverändert, ebenso das
  RAM-Limit von 8 GB für den Worker-Prozess.
- Zu niedrige Werte können zu Abstürzen des Qwen-Workers führen (nicht des Spiels). Das
  Spiel nutzt dann für den Rest der Sitzung die normale Stimme.

## Patch 2 im Detail

```
Spiel ──stdin/stdout──▶ QwenTtsWorker.exe (Proxy) ──HTTP──▶ TTS-Server im Heimnetz
       (Text + Stimmprobe)                        POST /v1/audio/speech
```

- Die originale `QwenTtsWorker.exe` wird gegen einen Proxy getauscht, der dasselbe
  Protokoll spricht. Die Prüfsumme in `runtime-manifest.json` wird angepasst.
- Der Hardware-Check gibt immer „geeignet“ zurück, und der Modell-Download entfällt.
- Ist der Server nicht erreichbar oder antwortet mit einem Fehler, nutzt das Spiel einfach
  die normale Stimme.

### Request an den Server

```json
{
  "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
  "input": "Hallo, hier ist Ihr Bankberater.",
  "voice": "default",
  "response_format": "wav",
  "language": "German",
  "ref_audio": "data:audio/wav;base64,UklGR…",
  "task_type": "Base",
  "x_vector_only_mode": true
}
```

- `ref_audio` ist die Stimmprobe der Spielfigur (24 kHz mono, höchstens 10 s). Damit
  sprechen alle Figuren mit ihrer eigenen Stimme, genau wie bei lokalem Qwen.
- Als Antwort wird WAV akzeptiert (jede Sample-Rate und Kanalzahl, 8/16/24/32 Bit oder
  Float). Alternativ `pcm` (16 Bit roh), das schon während des Downloads abgespielt wird.

### Server einrichten (Beispiel vLLM-Omni)

Auf einem Linux-Rechner mit NVIDIA-GPU:

```bash
pip install vllm-omni
```

```bash
vllm serve Qwen/Qwen3-TTS-12Hz-0.6B-Base --omni --host 0.0.0.0 --port 8000
```

Im Installer trägst du dann `http://<IP-des-Servers>:8000/v1/audio/speech` ein. Die
Felder für die Stimmprobe (`ref_audio`, `task_type`, `x_vector_only_mode`) hängen vom
Server und seiner Version ab. Mit **Verbindung testen** siehst du sofort, ob er sie
akzeptiert.

**Server ohne Voice-Cloning** (z. B. Kokoro-FastAPI, openedai-speech):
- „Stimmprobe mitsenden“ ausschalten und *Zusätzliche Felder* auf `{}` setzen.
- Als *Stimme* eine Stimme des Servers eintragen, z. B. `af_bella`.
- Eigene Stimmen pro Figur ordnest du über `voice_map` zu (siehe unten).

### Konfiguration

Der Installer schreibt
`Scam With Your Friends_Data\StreamingAssets\kolkata-qwen-runtime\qwen-remote.json`.
Vorlage: [config/qwen-remote.example.json](config/qwen-remote.example.json).

| Feld | Bedeutung |
|------|-----------|
| `url` | Vollständige Endpoint-URL. Die Umgebungsvariable `QWEN_REMOTE_URL` überschreibt sie. |
| `api_key` | Wird als `Authorization: Bearer …` gesendet, wenn gesetzt. |
| `model`, `voice` | Werden unverändert an den Server durchgereicht. |
| `response_format` | `wav` oder `pcm`. Bei `pcm` gibt `pcm_sample_rate` die Rate an (Standard 24000). |
| `timeout_seconds` | HTTP-Timeout. Das Spiel selbst gibt nach 20 s ohne Audio auf. |
| `send_language` | Sendet die Sprache als `language` mit (`English`, `German`, …). |
| `send_reference_audio` | Sendet die Stimmprobe der Figur mit. |
| `reference_audio_field` | Feldname für die Stimmprobe (Standard `ref_audio`). |
| `extra_body` | Wird 1:1 in jeden Request übernommen. |
| `voice_map` | Ordnet Stimmproben-Hashes Server-Stimmen zu, z. B. `{"88235bfe873b": "jake"}`. |
| `dump_references` | Speichert jede Stimmprobe einmal als `remote-voices\<hash>.wav`. Diese Dateien kannst du auf dem Server als feste Stimmen anlegen und über `voice_map` zuordnen. |

Die Datei kannst du direkt bearbeiten. Die Änderung gilt ab dem nächsten Laden von Qwen im
Spiel, neu patchen ist nicht nötig. Über **Runtime-Ordner öffnen** im Installer kommst du
zur Konfiguration, zum Log `qwen-remote.log` und zu `remote-voices`.

---

## Fehlersuche

| Symptom | Lösung |
|---------|--------|
| Spiel nutzt weiter die normale Stimme | „Qwen3 TTS“ in den Spracheinstellungen priorisiert? Im Installer: Status „Gepatcht“? |
| `qwen-remote.log`: *not reachable* | Server-IP und Port prüfen, Firewall auf dem Server öffnen, Server auf `0.0.0.0` lauschen lassen. |
| `HTTP 400/422` | Der Server kennt ein Feld nicht. *Zusätzliche Felder* auf `{}` setzen oder „Stimmprobe mitsenden“ ausschalten. |
| Stimme kommt verspätet oder bricht ab | Der Server ist zu langsam (Grenze: 20 s bis zum ersten Audio). Ein kleineres Modell oder `pcm` verwenden. |
| *unsupported game version* | Das Spiel-Update hat den Code geändert. Auf eine neue Patch-Version warten. |
| Unity-Log | `%USERPROFILE%\AppData\LocalLow\Jatater Worldwide\Scam With Your Friends\Player.log`, Einträge mit `[Qwen3 TTS]`. |

---

## Entwicklung

```
qwen_patcher/   Patch-Logik (core.py), Server-Test (remote.py)
installer.pyw   grafischer Installer (tkinter)
patch_qwen.py   Kommandozeile
worker/         Quelltext des Remote-Workers (C# 5, baut mit dem csc.exe von Windows)
tests/          Worker gegen Mock-Server; Patcher gegen eine Kopie der echten Spieldateien
tools/          Release-ZIP bauen
docs/           manuelle Installation, technische Details
```

```bash
py -m unittest discover -s tests -v
```

```bash
py tools/build_release.py
```

Die Patcher-Tests brauchen ein installiertes Spiel (wird über Steam gefunden oder per
`SWYF_GAME_DIR` gesetzt) und arbeiten nur auf Kopien. Technische Hintergründe stehen in
[docs/TECHNICAL.md](docs/TECHNICAL.md).

## Haftungsausschluss

Inoffizielles Fan-Projekt, nicht verbunden mit den Entwicklern des Spiels. Nutzung auf
eigene Gefahr. Vor Online-Partien mit Freunden alle Mitspieler informieren; der Patch
ändert nur die lokale Sprachausgabe.
