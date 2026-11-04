"""Builds dist/swyf-qwen-tts-patch-<version>.zip with prebuilt QwenRemoteWorker.exe and GladiaSttWorker.exe.

  py tools/build_release.py
"""
import os
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from qwen_patcher import VERSION, build_worker  # noqa: E402
from qwen_patcher.paths import BUNDLED_STT_WORKER, BUNDLED_WORKER, STT_WORKER_SOURCE  # noqa: E402


def tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line and not line.startswith((".git", "tests/", "tools/"))]


def main():
    build_worker(BUNDLED_WORKER)
    build_worker(BUNDLED_STT_WORKER, STT_WORKER_SOURCE)
    name = "swyf-qwen-tts-patch-%s" % VERSION
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    target = os.path.join(ROOT, "dist", name + ".zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in tracked_files() + [os.path.relpath(p, ROOT).replace(os.sep, "/") for p in (BUNDLED_WORKER, BUNDLED_STT_WORKER)]:
            z.write(os.path.join(ROOT, rel), name + "/" + rel)
    print("Built", target)


if __name__ == "__main__":
    main()
