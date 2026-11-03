"""Command line installer for the Qwen3-TTS patches (Scam With Your Friends).

  py patch_qwen.py --lowreq                    lower the Qwen3 hardware requirements
  py patch_qwen.py --lowreq --allow-cpu        ...and allow CPU-only systems
  py patch_qwen.py --remote --url http://...   offload TTS to a server
  py patch_qwen.py --test-server               test the configured server
  py patch_qwen.py --restore                   undo everything
  py patch_qwen.py --status

The game folder is detected through Steam; override it with --game-dir.
"""
import argparse
import json
import os
import sys

from qwen_patcher import Game, Options, PatchError, VERSION, find_game_dirs, load_config
from qwen_patcher.core import DEFAULTS, ORIGINAL, build_worker
from qwen_patcher.paths import EXAMPLE_CONFIG
from qwen_patcher.remote import test_server


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--game-dir", help="game folder (default: detected through Steam)")
    p.add_argument("--lowreq", action="store_true", help="lower the Qwen3 resource check")
    for key, unit in (("vram", "VRAM MiB"), ("ram", "system RAM MiB"), ("avail", "free RAM MiB")):
        p.add_argument("--" + key, type=int, default=DEFAULTS[key],
                       help="min %s (default %d, original %d)" % (unit, DEFAULTS[key], ORIGINAL[key]))
    p.add_argument("--threads", type=int, default=DEFAULTS["threads"], choices=range(0, 9),
                   help="min CPU threads (default %d, original %d)" % (DEFAULTS["threads"], ORIGINAL["threads"]))
    p.add_argument("--allow-cpu", action="store_true", help="allow systems without a suitable GPU (slow!)")
    p.add_argument("--keep-timeouts", action="store_true",
                   help="keep the game's Qwen timeouts (default: raise them so slow PCs/servers don't disable Qwen)")
    p.add_argument("--remote", action="store_true", help="send TTS to a server in the local network")
    p.add_argument("--config", help="server config JSON (default: keep the installed one, else the example)")
    p.add_argument("--url", help="server endpoint, e.g. http://192.168.1.50:8000/v1/audio/speech")
    p.add_argument("--test-server", action="store_true", help="send a test request to the server and exit")
    p.add_argument("--build-worker", action="store_true", help="only compile worker/QwenRemoteWorker.exe")
    p.add_argument("--restore", action="store_true", help="undo all patches")
    p.add_argument("--status", action="store_true")
    p.add_argument("--version", action="version", version=VERSION)
    args = p.parse_args()

    try:
        if args.build_worker:
            print("Built", build_worker())
            return 0

        game_dir = args.game_dir
        if not game_dir:
            found = find_game_dirs()
            if not found:
                raise PatchError("Game folder not found - pass --game-dir.")
            game_dir = found[0]
        game = Game(game_dir)
        print("Game:", game.root)

        if args.status:
            status, options = game.status()
            print("Status:", status)
            if options:
                print(json.dumps(options, indent=2))
            return 0
        if args.restore:
            game.uninstall()
            return 0

        config = None
        if args.config:
            config = load_config(args.config)
        elif args.url or not os.path.isfile(game.config):
            config = load_config(EXAMPLE_CONFIG)
        else:
            config = load_config(game.config)
        if args.url:
            config["url"] = args.url

        if args.test_server:
            print(test_server(config))
            return 0
        if not (args.lowreq or args.remote):
            p.print_help()
            return 1

        options = Options(lowreq=args.lowreq, remote=args.remote, allow_cpu=args.allow_cpu, vram=args.vram,
                          ram=args.ram, avail=args.avail, threads=args.threads, timeouts=not args.keep_timeouts)
        game.install(options, remote_config=config if args.remote else None)
        return 0
    except (PatchError, IOError, OSError, ValueError) as e:
        print("ERROR:", e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
