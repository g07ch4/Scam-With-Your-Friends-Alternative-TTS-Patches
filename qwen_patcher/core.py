"""Patch logic shared by the installer UI and the command line."""
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess

from .paths import BUNDLED_WORKER, WORKER_SOURCE

APP_ID = "4954910"

# QwenWorkerClient.HardwareEligible(...) - start of the IL body:
#   ldarg.s 5 ; ldc.i4 5632 ; blt.s ; ldarg.s 6 ; ldc.i4 4318 (NVIDIA) ; beq.s ; ldarg.s 6 ; ldc.i4 4098 (AMD)
ELIGIBLE_SIG = bytes.fromhex("0E05 2000160000 3250 0E06 20DE100000 2E09 0E06 2002100000".replace(" ", ""))
OFF_VRAM = 0x03       # ldc.i4 5632   -> min VRAM MiB
OFF_GPU_AND = 0x7D    # ldarg.0 ; ldloc.0 ; and   (windows64 && gpuOk)
OFF_RAM = 0x84        # ldc.i4 15000  -> min system RAM MiB
OFF_AVAIL = 0x8C      # ldc.i4 8192   -> min free RAM MiB
OFF_THREADS = 0x94    # ldc.i4.4      -> min CPU threads
ELIGIBLE_EXPECT = {
    OFF_VRAM - 1: b"\x20\x00\x16\x00\x00",
    OFF_GPU_AND: b"\x02\x06\x5F\x2C\x19",
    OFF_RAM - 1: b"\x20\x98\x3A\x00\x00\x32\x11",
    OFF_AVAIL - 1: b"\x20\x00\x20\x00\x00\x6A\x32\x08",
    OFF_THREADS: b"\x1A\xFE\x04\x16\xFE\x01\x2A\x16\x2A",
}

# QwenTtsModels.<RefreshPreference>d__23.MoveNext:
#   if (!supported) { SetState(5); leave }  if (verified) { SetState(3); leave }  -> download...
#   1B 28 <SetState> DD <x> 7E <verified> 2C 0B 19 28 <SetState> DD <x>
VERIFIED_RE = re.compile(rb"\x1B\x28(....)\xDD....\x7E....(\x2C\x0B)\x19\x28\1\xDD", re.S)

DEFAULTS = {"vram": 3072, "ram": 7000, "avail": 3072, "threads": 2}
ORIGINAL = {"vram": 5632, "ram": 15000, "avail": 8192, "threads": 4}


class PatchError(Exception):
    pass


class Options(object):
    def __init__(self, lowreq=False, remote=False, allow_cpu=False, vram=DEFAULTS["vram"], ram=DEFAULTS["ram"],
                 avail=DEFAULTS["avail"], threads=DEFAULTS["threads"]):
        self.lowreq, self.remote, self.allow_cpu = lowreq, remote, allow_cpu
        self.vram, self.ram, self.avail, self.threads = int(vram), int(ram), int(avail), int(threads)
        if not 0 <= self.threads <= 8:
            raise PatchError("threads must be between 0 and 8")
        if min(self.vram, self.ram, self.avail) < 0:
            raise PatchError("memory limits must not be negative")

    def to_dict(self):
        return dict(vars(self))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def is_game_dir(path):
    return bool(path) and os.path.isfile(os.path.join(path, "Scam With Your Friends_Data", "Managed",
                                                      "Assembly-CSharp.dll"))


def find_game_dirs():
    """Game folders from all Steam libraries (registry + libraryfolders.vdf)."""
    steam_roots = []
    try:
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for name in ("SteamPath", "InstallPath"):
                        try:
                            steam_roots.append(winreg.QueryValueEx(k, name)[0])
                        except OSError:
                            pass
            except OSError:
                pass
    except ImportError:
        pass
    steam_roots.append(r"C:\Program Files (x86)\Steam")

    libraries = []
    for root in steam_roots:
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        libraries.append(root)
        try:
            with open(vdf, encoding="utf-8", errors="replace") as f:
                libraries += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', f.read())]
        except OSError:
            pass

    found = []
    for lib in libraries:
        candidate = os.path.normpath(os.path.join(lib, "steamapps", "common", "Scam With Your Friends"))
        if is_game_dir(candidate) and candidate.lower() not in [x.lower() for x in found]:
            found.append(candidate)
    return found


def csc_path():
    root = os.environ.get("WINDIR", r"C:\Windows")
    for fw in ("Framework64", "Framework"):
        path = os.path.join(root, "Microsoft.NET", fw, "v4.0.30319", "csc.exe")
        if os.path.isfile(path):
            return path
    return None


def build_worker(out_path=BUNDLED_WORKER):
    """Compile QwenRemoteWorker.exe with the C# compiler that ships with Windows."""
    csc = csc_path()
    if not csc:
        raise PatchError(".NET Framework 4 C# compiler (csc.exe) not found.")
    result = subprocess.run([csc, "-nologo", "-optimize", "-platform:x64", "-target:exe",
                             "-r:System.Web.Extensions.dll", "-out:" + out_path, WORKER_SOURCE],
                            capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode != 0:
        raise PatchError("Building the worker failed:\n" + result.stdout + result.stderr)
    return out_path


def patch_dll(data, options, log=print):
    data = bytearray(data)
    base = data.find(ELIGIBLE_SIG)
    if base < 0 or data.find(ELIGIBLE_SIG, base + 1) >= 0:
        raise PatchError("HardwareEligible not found unambiguously - unsupported game version.")
    for off, expect in ELIGIBLE_EXPECT.items():
        if data[base + off:base + off + len(expect)] != expect:
            raise PatchError("HardwareEligible looks different than expected (offset 0x%X)." % off)

    if options.lowreq:
        struct.pack_into("<i", data, base + OFF_VRAM, options.vram)
        struct.pack_into("<i", data, base + OFF_RAM, options.ram)
        struct.pack_into("<i", data, base + OFF_AVAIL, options.avail)
        data[base + OFF_THREADS] = 0x16 + options.threads  # ldc.i4.<n>
        if options.allow_cpu:
            data[base + OFF_GPU_AND + 1] = 0x17  # ldloc.0 -> ldc.i4.1: GPU no longer required (backend "CPU")
        log("Hardware check: VRAM>=%d MiB, RAM>=%d MiB, free>=%d MiB, threads>=%d%s"
            % (options.vram, options.ram, options.avail, options.threads, ", CPU allowed" if options.allow_cpu else ""))

    if options.remote:
        # ldarg.0 ; ldloc.0 -> ldc.i4.1 ; ret   => always eligible (the server does the work)
        data[base + OFF_GPU_AND:base + OFF_GPU_AND + 2] = b"\x17\x2A"
        matches = list(VERIFIED_RE.finditer(bytes(data)))
        if len(matches) != 1:
            raise PatchError("Model check in RefreshPreference not found - unsupported game version.")
        at = matches[0].start(2)
        data[at:at + 2] = b"\x26\x00"  # brfalse.s -> pop ; nop  => model counts as installed, no 2 GB download
        log("Hardware check disabled, model download skipped (remote TTS)")
    return bytes(data)


def set_manifest_hash(text, digest):
    new, n = re.subn(r'("sha256"\s*:\s*")[0-9a-fA-F]{64}("\s*,\s*"path"\s*:\s*"QwenTtsWorker\.exe")',
                     lambda m: m.group(1) + digest + m.group(2), text)
    if n != 1:
        new, n = re.subn(r'("path"\s*:\s*"QwenTtsWorker\.exe"\s*,\s*"sha256"\s*:\s*")[0-9a-fA-F]{64}',
                         lambda m: m.group(1) + digest, text)
    if n != 1:
        raise PatchError("QwenTtsWorker.exe entry not found in runtime-manifest.json.")
    return new


class Game(object):
    def __init__(self, root):
        if not is_game_dir(root):
            raise PatchError("Not a 'Scam With Your Friends' folder: %s" % root)
        self.root = root
        data = os.path.join(root, "Scam With Your Friends_Data")
        self.dll = os.path.join(data, "Managed", "Assembly-CSharp.dll")
        self.runtime = os.path.join(data, "StreamingAssets", "kolkata-qwen-runtime")
        self.worker = os.path.join(self.runtime, "QwenTtsWorker.exe")
        self.manifest = os.path.join(self.runtime, "runtime-manifest.json")
        self.config = os.path.join(self.runtime, "qwen-remote.json")
        self.log_file = os.path.join(self.runtime, "qwen-remote.log")
        self.state_file = os.path.join(self.runtime, "qwen-patch-state.json")
        for path in (self.dll, self.worker, self.manifest):
            if not os.path.isfile(path):
                raise PatchError("Missing game file: %s" % path)

    # -------------------------------------------------------------- state

    def state(self):
        try:
            with open(self.state_file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_state(self, state):
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    def status(self):
        """'original', 'patched' (with options) or 'reverted' (game update / Steam verify)."""
        state = self.state()
        patched = state.get("patched")
        if not patched:
            return "original", None
        if all(sha256(p) == patched.get(os.path.basename(p)) for p in (self.dll, self.worker, self.manifest)):
            return "patched", state.get("options")
        return "reverted", state.get("options")

    def _original(self, path, state):
        """Return the pristine copy of `path`, refreshing the backup after a game update."""
        backup = path + ".orig"
        current = sha256(path)
        patched = state.get("patched", {}).get(os.path.basename(path))
        if not os.path.exists(backup) or (current != patched and current != sha256(backup)):
            shutil.copy2(path, backup)
        return backup

    # -------------------------------------------------------------- actions

    def install(self, options, remote_config=None, worker_exe=None, log=print):
        if not (options.lowreq or options.remote):
            raise PatchError("Nothing selected.")
        if options.remote:
            worker_exe = worker_exe or BUNDLED_WORKER
            if not os.path.isfile(worker_exe):
                log("Building QwenRemoteWorker.exe ...")
                build_worker(worker_exe)
            if remote_config is None and not os.path.isfile(self.config):
                raise PatchError("Remote TTS needs a server configuration.")

        state = self.state()
        for path in (self.dll, self.worker, self.manifest):
            self._original(path, state)

        # Build everything first so a failure leaves the game untouched.
        with open(self.dll + ".orig", "rb") as f:
            dll = patch_dll(f.read(), options, log)
        with open(self.manifest + ".orig", encoding="utf-8", newline="") as f:
            manifest = f.read()
        if options.remote:
            manifest = set_manifest_hash(manifest, sha256(worker_exe))

        with open(self.dll, "wb") as f:
            f.write(dll)
        if options.remote:
            shutil.copy2(worker_exe, self.worker)
            if remote_config is not None:
                write_config(self.config, remote_config)
            log("Remote worker installed, server: %s" % load_config(self.config).get("url"))
        else:
            shutil.copy2(self.worker + ".orig", self.worker)
        with open(self.manifest, "w", encoding="utf-8", newline="") as f:
            f.write(manifest)

        state["patched"] = {os.path.basename(p): sha256(p) for p in (self.dll, self.worker, self.manifest)}
        state["options"] = options.to_dict()
        self._save_state(state)
        log("Installed. Enable 'Qwen3 TTS' in the game's voice settings.")

    def uninstall(self, log=print):
        restored = False
        for path in (self.dll, self.worker, self.manifest):
            backup = path + ".orig"
            if os.path.exists(backup):
                shutil.copy2(backup, path)
                os.remove(backup)
                restored = True
                log("Restored %s" % os.path.relpath(path, self.root))
        if os.path.exists(self.state_file):
            os.remove(self.state_file)
        log("Original files restored." if restored else "Nothing to restore.")


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_config(path, config):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
