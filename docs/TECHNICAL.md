# Technical details

The game is a Unity Mono build. The Qwen3 TTS integration lives in the `Kolkata.QwenTts`
namespace in `Assembly-CSharp.dll`. Synthesis itself happens in a separate process,
`StreamingAssets/kolkata-qwen-runtime/QwenTtsWorker.exe`: a small .NET application that
calls `audiocpp.dll` (audio.cpp/ggml, CUDA or Vulkan) through P/Invoke.

## Hardware check

`QwenWorkerClient.TryChooseBackend` passes values from `SystemInfo` and
`GlobalMemoryStatusEx` to:

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

Patch 1 changes the four constants (`ldc.i4` operands and `ldc.i4.<n>`). `--allow-cpu`
replaces `ldloc.0` (gpu) in the return expression with `ldc.i4.1`. Patch 2 replaces
`ldarg.0; ldloc.0` at the start of the return expression with `ldc.i4.1; ret`.

Every change has the same length as the original. Method headers, tokens and branch
targets stay valid, and the code after `ret` is unreachable but still valid IL.

## Model download

In `QwenTtsModels.<RefreshPreference>d__23.MoveNext`:

```
IL_0104: ldsfld  QwenTtsModels::verified
IL_0109: brfalse.s IL_0116        ; -> pop ; nop
IL_010B: ldc.i4.3
IL_010C: call    QwenTtsModels::SetState(QwenDownloadState)   ; 3 = Ready
```

With patch 2 the model always counts as installed. The proxy worker ignores the model
path.

## Speech provider choice and timeouts

For every caller line, `PocketTtsSingleton.ProcessSpeakQueue` uses Qwen only if:

```
QwenTtsProgress.HardwareSupported                     (result of HardwareEligible)
&& the first enabled model in the language's list is Qwen (SpeechModelPreferences, per language)
&& QwenTtsModels.State == Ready
&& !QwenTtsSingleton.FailedThisSession
&& QwenTtsSingleton.Status == Ready after Prepare()
```

Otherwise it takes the first enabled non-Qwen model (`SpeechModelPreferences.LegacyModel`).
If there is none, the line is completed silently.

`QwenTtsSingleton.Fail()` sets `FailedThisSession`, which stays set until the game restarts.
It is called on worker errors and when one of these limits expires:

| Where | IL | Original | Patched |
|-------|----|---------:|--------:|
| `<Prepare>d__44.MoveNext` | `new CancellationTokenSource(TimeSpan.FromSeconds(20))` | 20 | 120 |
| `<Prepare>d__44.MoveNext` | `expires = realtimeSinceStartup + 20` | 20 | 120 |
| `Prompt` | `firstAudioDeadline = realtimeSinceStartup + 20` | 20 | 60 |
| `Prompt` | `new CancellationTokenSource(TimeSpan.FromSeconds(30))` | 30 | 90 |
| `<Prompt>b__2` | `activeCancellation.CancelAfter(TimeSpan.FromSeconds(30))` per chunk | 30 | 60 |

The patcher finds each `ldc.r8` through its surrounding opcodes, with wildcards for the
metadata tokens, and replaces the 8-byte double.

Preparation runs `QwenRuntimeFiles.Validate` first, which hashes all 49 manifest files
(about 1,061 MiB) with Mono's SHA-256 once per session. In remote mode the manifest lists
only `QwenTtsWorker.exe` and the four license files. `Validate` requires at least 4 entries.

## Worker protocol

Binary over stdin/stdout (`BinaryWriter`/`BinaryReader`; strings are UTF-8 with a 7-bit
length prefix).

| Direction | Message |
|-----------|---------|
| Game → worker | `1`, `model:str`, `backend:str` (`CPU`/`CUDA`/`Vulkan0`) |
| Worker → game | `1`, `2` (protocol version), `backend:str` (`cpu`/`cuda`/`vulkan`) |
| Game → worker | `2`, `text:str` (≤ 240 characters per chunk), `language:str`, `n:i32`, `n × f32` voice sample (24 kHz mono, 0.1–10 s; `n = 0` means "same as last time") |
| Worker → game | any number of `2`, `count:i32`, `count × f32` (24 kHz mono, −1…1), then `3` |
| Worker → game | on error: `4`, `message:str` |

Limits on the game side:
- At most 720,000 samples (30 s) per request.
- The time limits from the table above.
- The worker runs in a job object with an 8 GB memory limit.

The remote worker splits each text at sentence ends, merges short sentences up to
`max_segment_chars`, and sends one HTTP request per segment, emitting audio as soon as each
segment arrives.

The original worker calls audio.cpp with `x_vector_only_mode=true` and `max_tokens=360`,
i.e. voice cloning from the speaker embedding without a transcript. The proxy maps this to
the OpenAI speech API using `ref_audio` + `x_vector_only_mode` + `task_type: Base`.

## Runtime validation

`QwenRuntimeFiles.Validate` reads `runtime-manifest.json` and checks:
- `source == "0xShug0/audio.cpp"`, the commit and `protocol == 2`;
- the SHA-256 of every file listed there.

The expected hashes exist only in the manifest, not in the code, so the patcher can rewrite
the file list freely.

## Backups and updates

- The patcher creates `<file>.orig` next to every file it changes. It keeps its state in
  `kolkata-qwen-runtime/qwen-patch-state.json`, including the hashes of the patched files.
- Every installation starts from the `.orig` files. If a file differs both from the
  patched state and from the backup, an update has replaced it, and it is backed up as the
  new original.
