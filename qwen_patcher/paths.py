import os

PACKAGE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(PACKAGE)
WORKER_SOURCE = os.path.join(ROOT, "worker", "QwenRemoteWorker.cs")
BUNDLED_WORKER = os.path.join(ROOT, "worker", "QwenRemoteWorker.exe")
EXAMPLE_CONFIG = os.path.join(ROOT, "config", "qwen-remote.example.json")
STT_WORKER_SOURCE = os.path.join(ROOT, "worker", "GladiaSttWorker.cs")
BUNDLED_STT_WORKER = os.path.join(ROOT, "worker", "GladiaSttWorker.exe")
STT_EXAMPLE_CONFIG = os.path.join(ROOT, "config", "gladia.example.json")
VERSION = "1.2.0"
