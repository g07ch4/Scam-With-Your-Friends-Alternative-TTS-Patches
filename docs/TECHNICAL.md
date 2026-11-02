# Technische Details

Das Spiel ist ein Unity-Mono-Build. Die Qwen3-TTS-Integration liegt im Namespace
`Kolkata.QwenTts` in `Assembly-CSharp.dll`. Die Synthese selbst übernimmt ein separater
Prozess, `StreamingAssets/kolkata-qwen-runtime/QwenTtsWorker.exe`. Das ist eine kleine
.NET-Anwendung, die per P/Invoke `audiocpp.dll` (audio.cpp/ggml, CUDA oder Vulkan) nutzt.

## Hardware-Check

`QwenWorkerClient.TryChooseBackend` übergibt Werte aus `SystemInfo` und
`GlobalMemoryStatusEx` an:

```csharp
static bool HardwareEligible(bool windows64, int ramMb, long availableMb, int threads,
                             int frequencyMhz, int vramMb, int vendor, int device, out string backend)
{
    bool gpu = vramMb >= 5632
            && (vendor == 0x10DE || vendor == 0x1002)                                // NVIDIA / AMD
            && !(vendor == 0x1002 && (device == 27039 || device == 26591 || device == 29772))
            && !(vendor == 0x10DE && device == 11141);
    backend = !gpu ? "CPU" : vendor == 0x10DE ? "CUDA" : "Vulkan0";
    return windows64 & gpu && ramMb >= 15000 && availableMb >= 8192 && threads >= 4;
}
```

Patch 1 ändert die vier Konstanten (`ldc.i4`-Operanden bzw. `ldc.i4.<n>`). `--allow-cpu`
ersetzt `ldloc.0` (gpu) im Rückgabeausdruck durch `ldc.i4.1`. Patch 2 ersetzt
`ldarg.0; ldloc.0` am Anfang des Rückgabeausdrucks durch `ldc.i4.1; ret`.

Alle Änderungen haben dieselbe Länge wie das Original. Methodenheader, Tokens und
Sprungziele bleiben gültig, und der Code nach `ret` ist zwar unerreichbar, aber gültiges IL.

## Modell-Download

In `QwenTtsModels.<RefreshPreference>d__23.MoveNext`:

```
IL_0104: ldsfld  QwenTtsModels::verified
IL_0109: brfalse.s IL_0116        ; -> pop ; nop
IL_010B: ldc.i4.3
IL_010C: call    QwenTtsModels::SetState(QwenDownloadState)   ; 3 = Ready
```

Mit Patch 2 gilt das Modell immer als vorhanden. Der Proxy-Worker ignoriert den
Modellpfad.

## Worker-Protokoll

Binär über stdin/stdout (`BinaryWriter`/`BinaryReader`; Strings mit 7-Bit-Längenpräfix
in UTF-8).

| Richtung | Nachricht |
|----------|-----------|
| Spiel → Worker | `1`, `model:str`, `backend:str` (`CPU`/`CUDA`/`Vulkan0`) |
| Worker → Spiel | `1`, `2` (Protokollversion), `backend:str` (`cpu`/`cuda`/`vulkan`) |
| Spiel → Worker | `2`, `text:str` (≤ 240 Zeichen pro Chunk), `language:str`, `n:i32`, `n × f32` Stimmprobe (24 kHz mono, 0,1–10 s; `n = 0` heißt „wie zuletzt“) |
| Worker → Spiel | beliebig oft `2`, `count:i32`, `count × f32` (24 kHz mono, −1…1), danach `3` |
| Worker → Spiel | bei Fehler `4`, `message:str` |

Grenzen auf Spielseite:
- Höchstens 720 000 Samples (30 s) pro Request.
- Kommt nach 20 s noch kein erstes Audio, gibt das Spiel auf; nach 30 s bricht es den
  ganzen Request ab.
- Der Worker läuft in einem Job-Objekt mit 8 GB Speicherlimit.

Das Original-Worker ruft audio.cpp mit `x_vector_only_mode=true` und `max_tokens=360`
auf, also Voice-Cloning über das Sprecher-Embedding ohne Transkript. Der Proxy bildet das
mit `ref_audio` + `x_vector_only_mode` + `task_type: Base` auf die OpenAI-Speech-API ab.

## Runtime-Validierung

`QwenRuntimeFiles.Validate` liest `runtime-manifest.json` und prüft:
- `source == "0xShug0/audio.cpp"`, den Commit und `protocol == 2`;
- den SHA-256 jeder dort gelisteten Datei.

Die erwarteten Hashes stehen nur im Manifest und nicht im Code. Deshalb genügt es, den
Eintrag für `QwenTtsWorker.exe` zu aktualisieren.

## Backups und Updates

- Der Patcher legt `<datei>.orig` neben jeder geänderten Datei an. Seinen Zustand
  speichert er in `kolkata-qwen-runtime/qwen-patch-state.json`, inklusive der Hashes der
  gepatchten Dateien.
- Jede Installation baut auf den `.orig`-Dateien auf. Unterscheidet sich eine Datei sowohl
  vom gepatchten Stand als auch vom Backup, hat ein Update sie ersetzt. Dann wird sie als
  neues Original gesichert.
