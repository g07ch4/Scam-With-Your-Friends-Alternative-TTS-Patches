# Manuelle Installation (ohne Python)

Diese Anleitung gilt für den Spielstand vom **29.10.2026**, erkennbar an diesem SHA-256 von
`Assembly-CSharp.dll`:

```
bc111bc14cd7552b0c8de4d21a686728aaeaa23b3713dc1642bf36c0b5b03528
```

Den Hash zeigt dir PowerShell an:

```powershell
Get-FileHash "Scam With Your Friends_Data\Managed\Assembly-CSharp.dll"
```

Bei einem anderen Hash passen die Hex-Muster unten wahrscheinlich nicht. Dann den
grafischen Installer verwenden: Er sucht die Stellen robuster.

Du brauchst einen Hex-Editor, z. B. [HxD](https://mh-nexus.de/de/hxd/) (kostenlos).
Alle Pfade sind relativ zum Spielordner `…\steamapps\common\Scam With Your Friends`.

## 0. Backups anlegen

Diese Dateien kopieren und an die Kopie `.orig` anhängen:

- `Scam With Your Friends_Data\Managed\Assembly-CSharp.dll`
- `Scam With Your Friends_Data\StreamingAssets\kolkata-qwen-runtime\QwenTtsWorker.exe`
- `Scam With Your Friends_Data\StreamingAssets\kolkata-qwen-runtime\runtime-manifest.json`

Rückgängig machen: Die `.orig`-Dateien zurückkopieren, oder in Steam „Dateien auf Fehler
überprüfen“.

## 1. Patch 1 – Hardware-Anforderungen senken

`Assembly-CSharp.dll` in HxD öffnen. **Suchen → Ersetzen** (Strg+R), Datentyp
**Hexadezimal-Werte**. Jede Suche muss genau **1** Treffer haben.

**a) VRAM 5632 → 3072 MiB**

| | Hex |
|---|---|
| Suchen | `0E 05 20 00 16 00 00 32 50 0E 06` |
| Ersetzen | `0E 05 20 00 0C 00 00 32 50 0E 06` |

**b) RAM 15000 → 7000, freier RAM 8192 → 3072, Threads 4 → 2**

| | Hex |
|---|---|
| Suchen | `02 06 5F 2C 19 03 20 98 3A 00 00 32 11 04 20 00 20 00 00 6A 32 08 05 1A FE 04` |
| Ersetzen | `02 06 5F 2C 19 03 20 58 1B 00 00 32 11 04 20 00 0C 00 00 6A 32 08 05 18 FE 04` |

Optional **auch ohne GPU (CPU)**: im Ersetzen-Wert von b) das zweite Byte `06` durch `17`
ersetzen, also `02 17 5F 2C 19 …`.

Eigene Werte: Die Zahlen stehen als 32-Bit-Little-Endian im Code.
- Beispiel: 4096 = `0x1000` → `00 10 00 00`.
- VRAM sind die 4 Bytes nach `0E 05 20`, RAM die nach `03 20`, freier RAM die nach `04 20`.
- Threads ist ein einzelnes Byte direkt vor `FE 04`: `16` + Anzahl, also `16` = 0 bis
  `1E` = 8.

Speichern, fertig. Im Spiel „Qwen3 TTS“ priorisieren; das Modell wird beim ersten Mal
heruntergeladen (ca. 2 GB).

## 2. Patch 2 – TTS auf einen Server auslagern

### 2a. DLL patchen

Wenn du Patch 1 schon angewendet hast: zuerst die Original-DLL aus dem Backup
zurückkopieren. Patch 2 hebt den Hardware-Check ohnehin ganz auf.

**Hardware-Check aus**

| | Hex |
|---|---|
| Suchen | `02 06 5F 2C 19 03 20 98 3A 00 00 32 11 04 20 00 20 00 00 6A 32 08 05 1A FE 04` |
| Ersetzen | `17 2A 5F 2C 19 03 20 98 3A 00 00 32 11 04 20 00 20 00 00 6A 32 08 05 1A FE 04` |

**Modell-Download überspringen**

| | Hex |
|---|---|
| Suchen | `7E 9E 13 00 04 2C 0B 19 28 8B 18 00 06` |
| Ersetzen | `7E 9E 13 00 04 26 00 19 28 8B 18 00 06` |

### 2b. Worker austauschen

1. `QwenRemoteWorker.exe` besorgen: Sie liegt im Release-ZIP im Ordner `worker\`.
   Alternativ selbst bauen mit `worker\build_worker.cmd` (nutzt den C#-Compiler von
   Windows).
2. Die Datei nach `…\kolkata-qwen-runtime\` kopieren und in **`QwenTtsWorker.exe`**
   umbenennen. Das Original wird überschrieben; das Backup hast du in Schritt 0 angelegt.
3. `config\qwen-remote.example.json` nach `…\kolkata-qwen-runtime\qwen-remote.json`
   kopieren und `url` anpassen.

### 2c. Prüfsumme im Manifest anpassen

```powershell
(Get-FileHash "Scam With Your Friends_Data\StreamingAssets\kolkata-qwen-runtime\QwenTtsWorker.exe").Hash.ToLower()
```

In `runtime-manifest.json` den Eintrag mit `"path": "QwenTtsWorker.exe"` suchen und dessen
`"sha256"` durch diesen Wert ersetzen. Ohne diesen Schritt meldet das Spiel *„Qwen
runtime checksum mismatch“* und bleibt bei der normalen Stimme.

### 2d. Testen

Im Spiel „Qwen3 TTS“ priorisieren und einen Anruf starten. In
`…\kolkata-qwen-runtime\qwen-remote.log` sollten Zeilen wie diese erscheinen:

```
loaded; server http://192.168.1.50:8000/v1/audio/speech
ok voice=default ref=88235bfe873b lang=German chars=42 audio=3,1s took=0,84s
```
