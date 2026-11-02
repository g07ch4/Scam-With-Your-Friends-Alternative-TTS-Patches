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

### 2c. Update the checksum in the manifest

```powershell
(Get-FileHash "Scam With Your Friends_Data\StreamingAssets\kolkata-qwen-runtime\QwenTtsWorker.exe").Hash.ToLower()
```

In `runtime-manifest.json`, find the entry with `"path": "QwenTtsWorker.exe"` and replace
its `"sha256"` with this value. Without this step the game reports *"Qwen runtime checksum
mismatch"* and keeps its regular voice.

### 2d. Test

Prioritize "Qwen3 TTS" in the game and start a call. Lines like these should appear in
`…\kolkata-qwen-runtime\qwen-remote.log`:

```
loaded; server http://192.168.1.50:8000/v1/audio/speech
ok voice=default ref=88235bfe873b lang=English chars=42 audio=3.1s took=0.84s
```
