# Manual installation (without Python)

These instructions apply to the game build from **October 29, 2026**, which you can
recognize by this SHA-256 of `Assembly-CSharp.dll`:

```
bc111bc14cd7552b0c8de4d21a686728aaeaa23b3713dc1642bf36c0b5b03528
```

PowerShell shows you the hash:

```powershell
Get-FileHash "Scam With Your Friends_Data\Managed\Assembly-CSharp.dll"
```

If the hash is different, the hex patterns below probably won't match. Use the graphical
installer instead: it locates the code more robustly.

You need a hex editor such as [HxD](https://mh-nexus.de/en/hxd/) (free). All paths are
relative to the game folder `…\steamapps\common\Scam With Your Friends`.

## 0. Make backups

Copy these files and add `.orig` to the name of each copy:

- `Scam With Your Friends_Data\Managed\Assembly-CSharp.dll`
- `Scam With Your Friends_Data\StreamingAssets\kolkata-qwen-runtime\QwenTtsWorker.exe`
- `Scam With Your Friends_Data\StreamingAssets\kolkata-qwen-runtime\runtime-manifest.json`

To undo: copy the `.orig` files back, or use Steam's "Verify integrity of game files".

## 1. Patch 1 – Lower the hardware requirements

Open `Assembly-CSharp.dll` in HxD. Use **Search → Replace** (Ctrl+R) with the data type
**Hex-values**. Each search must have exactly **1** match.

**a) VRAM 5632 → 3072 MiB**

| | Hex |
|---|---|
| Find | `0E 05 20 00 16 00 00 32 50 0E 06` |
| Replace | `0E 05 20 00 0C 00 00 32 50 0E 06` |

**b) RAM 15000 → 7000, free RAM 8192 → 3072, threads 4 → 2**

| | Hex |
|---|---|
| Find | `02 06 5F 2C 19 03 20 98 3A 00 00 32 11 04 20 00 20 00 00 6A 32 08 05 1A FE 04` |
| Replace | `02 06 5F 2C 19 03 20 58 1B 00 00 32 11 04 20 00 0C 00 00 6A 32 08 05 18 FE 04` |

Optional, **also without a GPU (CPU)**: in the replacement value of b), change the second
byte from `06` to `17`, i.e. `02 17 5F 2C 19 …`.

Custom values: the numbers are stored as 32-bit little-endian in the code.
- Example: 4096 = `0x1000` → `00 10 00 00`.
- VRAM is the 4 bytes after `0E 05 20`, RAM the 4 bytes after `03 20`, free RAM the 4
  bytes after `04 20`.
- Threads is a single byte right before `FE 04`: `16` + count, i.e. from `16` = 0 to
  `1E` = 8.

Save, and you're done. Prioritize "Qwen3 TTS" in the game; the model (about 2 GB) is
downloaded the first time.

## 2. Patch 2 – Offload TTS to a server

### 2a. Patch the DLL

If you already applied patch 1, first copy the original DLL back from the backup. Patch 2
removes the hardware check completely anyway.

**Turn off the hardware check**

| | Hex |
|---|---|
| Find | `02 06 5F 2C 19 03 20 98 3A 00 00 32 11 04 20 00 20 00 00 6A 32 08 05 1A FE 04` |
| Replace | `17 2A 5F 2C 19 03 20 98 3A 00 00 32 11 04 20 00 20 00 00 6A 32 08 05 1A FE 04` |

**Skip the model download**

| | Hex |
|---|---|
| Find | `7E 9E 13 00 04 2C 0B 19 28 8B 18 00 06` |
| Replace | `7E 9E 13 00 04 26 00 19 28 8B 18 00 06` |

### 2b. Replace the worker

1. Get `QwenRemoteWorker.exe`: it's in the `worker\` folder of the release ZIP. Or build
   it yourself with `worker\build_worker.cmd`, which uses the C# compiler that ships with
   Windows.
2. Copy the file to `…\kolkata-qwen-runtime\` and rename it to **`QwenTtsWorker.exe`**.
   This overwrites the original; you made a backup in step 0.
3. Copy `config\qwen-remote.example.json` to `…\kolkata-qwen-runtime\qwen-remote.json` and
   set `url`.

### 2c. Update the manifest

The game hashes every file listed in `runtime-manifest.json` before it starts the worker.
The remote worker needs none of the ~1 GB of CUDA/Vulkan DLLs, and hashing them can take
longer than the game's preparation limit on slow PCs. So list only the worker and the
license files.

Run this in PowerShell from the game folder:

```powershell
$rt = "Scam With Your Friends_Data\StreamingAssets\kolkata-qwen-runtime"
$m = Get-Content "$rt\runtime-manifest.json" -Raw | ConvertFrom-Json
$m.files = @("QwenTtsWorker.exe", "LICENSE-audio.cpp.txt", "LICENSE-lookbe.txt", "LICENSE-model.txt", "LICENSE-qwentts.txt") |
  ForEach-Object { [pscustomobject]@{ sha256 = (Get-FileHash "$rt\$_").Hash.ToLower(); path = $_ } }
$m | ConvertTo-Json -Depth 5 | Set-Content "$rt\runtime-manifest.json" -Encoding UTF8
```

Without this step the game reports *"Qwen runtime checksum mismatch"* and keeps its regular
voice.

### 2d. Test

Prioritize "Qwen3 TTS" in the game and start a call. Lines like these should appear in
`…\kolkata-qwen-runtime\qwen-remote.log`:

```
loaded; server http://192.168.1.50:8000/v1/audio/speech
ok voice=default ref=88235bfe873b lang=English chars=42 parts=1 audio=3.1s first=0.84s took=0.84s
```

## 3. Raise the Qwen timeouts (recommended for patches 1 and 2)

A single Qwen timeout turns Qwen off until the game restarts. If no other speech model is
enabled, callers then stay silent. These replacements in `Assembly-CSharp.dll` raise the
limits: preparation 20 → 120 s, first audio 20 → 60 s, synthesis 30 → 90 s, and 30 → 60 s
between audio chunks. Apply them on top of patch 1 or 2; each search must have exactly
**1** match.

**Preparation, cancellation (20 → 120 s)**

| | Hex |
|---|---|
| Find | `17 28 C3 0F 00 0A 07 23 00 00 00 00 00 00 34 40 28 B5 01 00 0A 73 FF 01 00 0A 7D` |
| Replace | `17 28 C3 0F 00 0A 07 23 00 00 00 00 00 00 5E 40 28 B5 01 00 0A 73 FF 01 00 0A 7D` |

**Preparation, deadline (20 → 120 s)**

| | Hex |
|---|---|
| Find | `08 28 B4 01 00 0A 23 00 00 00 00 00 00 34 40 58 7D` |
| Replace | `08 28 B4 01 00 0A 23 00 00 00 00 00 00 5E 40 58 7D` |

**First audio (20 → 60 s)**

| | Hex |
|---|---|
| Find | `02 28 B4 01 00 0A 23 00 00 00 00 00 00 34 40 58 7D E4 13 00 04 02 06 FE 06` |
| Replace | `02 28 B4 01 00 0A 23 00 00 00 00 00 00 4E 40 58 7D E4 13 00 04 02 06 FE 06` |

**Synthesis (30 → 90 s)**

| | Hex |
|---|---|
| Find | `7D F7 13 00 04 02 23 00 00 00 00 00 00 3E 40 28 B5 01 00 0A 73 FF 01 00 0A 7D` |
| Replace | `7D F7 13 00 04 02 23 00 00 00 00 00 80 56 40 28 B5 01 00 0A 73 FF 01 00 0A 7D` |

**Between audio chunks (30 → 60 s)**

| | Hex |
|---|---|
| Find | `7B FB 13 00 04 23 00 00 00 00 00 00 3E 40 28 B5 01 00 0A 6F C8 01 00 0A 02 03 02 7B` |
| Replace | `7B FB 13 00 04 23 00 00 00 00 00 00 4E 40 28 B5 01 00 0A 6F C8 01 00 0A 02 03 02 7B` |

## 4. Patch 3 – Speech recognition through Gladia

Make backups first (add `.orig`):

- `Scam With Your Friends_Data\Managed\ScriptsAssDef.dll`
- `Scam With Your Friends_Data\StreamingAssets\Moonshine\runtime\ArmSpeechWorker.exe`
- `Scam With Your Friends_Data\StreamingAssets\Moonshine\runtime\runtime-manifest.json`

### 4a. Patch `ScriptsAssDef.dll`

Open it in HxD and use **Search → Replace** with **Hex-values**; each search must have exactly
**1** match. The values below belong to the October 29, 2026 build.

**Always use the Moonshine helper** (`WindowsSpeechCompatibility.PreferMoonshine`)

| | Hex |
|---|---|
| Find | `28 5D 3A 00 06 3A 82 00 00 00 7E E5` |
| Replace | `17 2A 3A 00 06 3A 82 00 00 00 7E E5` |

**The helper handles every language** (`MoonshineStreamingRuntime.SupportsLanguage`)

| | Hex |
|---|---|
| Find | `02 72 FA 54 00 70 28 13 00 00 0A 2D 33 02` |
| Replace | `17 2A FA 54 00 70 28 13 00 00 0A 2D 33 02` |

**No partial transcripts** (optional, recommended: one Gladia request per utterance)

| | Hex |
|---|---|
| Find | `28 5D 3A 00 06 2C 09 02 7B 5E 2C 00 04 2C 01 2A 04 2D 16 02 7B 50 2C 00 04` |
| Replace | `28 5D 3A 00 06 2C 09 02 7B 5E 2C 00 04 2C 01 2A 04 2D 16 2A 7B 50 2C 00 04` |

### 4b. Replace the helper

1. Copy `worker\GladiaSttWorker.exe` from the release ZIP to `…\Moonshine\runtime\` and rename it
   to **`ArmSpeechWorker.exe`**.
2. Copy `config\gladia.example.json` to `…\Moonshine\runtime\gladia.json` and enter your `api_key`.

### 4c. Update the manifest

Run this in PowerShell from the game folder:

```powershell
$rt = "Scam With Your Friends_Data\StreamingAssets\Moonshine\runtime"
$m = Get-Content "$rt\runtime-manifest.json" -Raw | ConvertFrom-Json
$files = [ordered]@{}
foreach ($n in "ArmSpeechWorker.exe", "ArmSpeechNative.dll", "moonshine-LICENSE.txt") { $files[$n] = (Get-FileHash "$rt\$n").Hash.ToLower() }
$m.files = [pscustomobject]$files
$m | ConvertTo-Json -Depth 5 | Set-Content "$rt\runtime-manifest.json" -Encoding UTF8
```

### 4d. Test

Start a call and speak. `…\Moonshine\runtime\gladia.log` should show lines like
`ok lang=en audio=1.8s took=1.40s conf=0.92 text="hello, who is this?"`.
