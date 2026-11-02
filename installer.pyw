"""Graphical installer for the Qwen3-TTS patches (Scam With Your Friends)."""
import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qwen_patcher import Game, Options, PatchError, VERSION, find_game_dirs, load_config  # noqa: E402
from qwen_patcher.core import DEFAULTS, ORIGINAL, is_game_dir  # noqa: E402
from qwen_patcher.paths import EXAMPLE_CONFIG  # noqa: E402
from qwen_patcher.remote import test_server  # noqa: E402

STATUS_TEXT = {
    "original": "Nicht gepatcht",
    "patched": "Gepatcht",
    "reverted": "Patch wurde durch ein Spiel-Update entfernt – bitte neu installieren",
}


class Installer(tk.Tk):
    def __init__(self):
        tk.Tk.__init__(self)
        self.title("Scam With Your Friends – Qwen3 TTS Patch %s" % VERSION)
        self.minsize(640, 600)
        self.events = queue.Queue()
        self.busy = False

        self.game_dir = tk.StringVar()
        self.status = tk.StringVar(value="–")
        self.lowreq = tk.BooleanVar(value=True)
        self.allow_cpu = tk.BooleanVar(value=False)
        self.limits = {k: tk.IntVar(value=v) for k, v in DEFAULTS.items()}
        self.remote = tk.BooleanVar(value=False)
        self.fields = {k: tk.StringVar() for k in ("url", "api_key", "model", "voice", "response_format",
                                                    "timeout_seconds", "reference_audio_field")}
        self.send_reference = tk.BooleanVar()
        self.send_language = tk.BooleanVar()
        self.dump_references = tk.BooleanVar()

        self._build()
        self._load_config(load_config(EXAMPLE_CONFIG))
        dirs = find_game_dirs()
        self.game_combo["values"] = dirs
        if dirs:
            self.game_dir.set(dirs[0])
        self.game_dir.trace_add("write", lambda *_: self.refresh())
        self.refresh()
        self._toggle()
        self.after(100, self._pump)

    # ---------------------------------------------------------------- layout

    def _build(self):
        pad = {"padx": 8, "pady": 4}
        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)

        game = ttk.LabelFrame(body, text="Spielordner", padding=8)
        game.grid(row=0, column=0, sticky="ew", **pad)
        game.columnconfigure(0, weight=1)
        self.game_combo = ttk.Combobox(game, textvariable=self.game_dir)
        self.game_combo.grid(row=0, column=0, sticky="ew")
        ttk.Button(game, text="Durchsuchen…", command=self._browse).grid(row=0, column=1, padx=(6, 0))
        ttk.Label(game, textvariable=self.status, foreground="#555").grid(row=1, column=0, columnspan=2, sticky="w",
                                                                          pady=(4, 0))

        low = ttk.LabelFrame(body, text="Patch 1 – Hardware-Anforderungen senken", padding=8)
        low.grid(row=1, column=0, sticky="ew", **pad)
        ttk.Checkbutton(low, text="Aktivieren", variable=self.lowreq, command=self._toggle).grid(
            row=0, column=0, columnspan=4, sticky="w")
        self.low_widgets = []
        labels = (("vram", "Min. VRAM (MiB)", 0, 65536), ("ram", "Min. RAM (MiB)", 0, 262144),
                  ("avail", "Min. freier RAM (MiB)", 0, 262144), ("threads", "Min. CPU-Threads", 0, 8))
        for i, (key, text, lo, hi) in enumerate(labels):
            r, c = 1 + i // 2, (i % 2) * 2
            ttk.Label(low, text="%s, orig. %d" % (text, ORIGINAL[key])).grid(row=r, column=c, sticky="w", pady=2)
            spin = ttk.Spinbox(low, from_=lo, to=hi, increment=1 if key == "threads" else 256,
                               textvariable=self.limits[key], width=8)
            spin.grid(row=r, column=c + 1, sticky="w", padx=(6, 24))
            self.low_widgets.append(spin)
        cpu = ttk.Checkbutton(low, text="Auch ohne passende GPU auf der CPU (meist zu langsam)",
                              variable=self.allow_cpu)
        cpu.grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))
        self.low_widgets.append(cpu)

        rem = ttk.LabelFrame(body, text="Patch 2 – TTS an Server im Heimnetz auslagern (OpenAI /v1/audio/speech)",
                             padding=8)
        rem.grid(row=2, column=0, sticky="ew", **pad)
        rem.columnconfigure(1, weight=1)
        ttk.Checkbutton(rem, text="Aktivieren", variable=self.remote, command=self._toggle).grid(
            row=0, column=0, columnspan=3, sticky="w")
        self.remote_widgets = []
        rows = (("url", "Server-URL"), ("api_key", "API-Key (optional)"), ("model", "Modell"),
                ("voice", "Stimme (Fallback)"))
        for i, (key, text) in enumerate(rows, start=1):
            ttk.Label(rem, text=text).grid(row=i, column=0, sticky="w", pady=2)
            entry = ttk.Entry(rem, textvariable=self.fields[key], show="•" if key == "api_key" else "")
            entry.grid(row=i, column=1, columnspan=2, sticky="ew", padx=(6, 0))
            self.remote_widgets.append(entry)
        ttk.Label(rem, text="Format / Timeout (s)").grid(row=5, column=0, sticky="w", pady=2)
        fmt = ttk.Frame(rem)
        fmt.grid(row=5, column=1, columnspan=2, sticky="w", padx=(6, 0))
        combo = ttk.Combobox(fmt, textvariable=self.fields["response_format"], values=("wav", "pcm"),
                             state="readonly", width=6)
        combo.pack(side="left")
        timeout = ttk.Spinbox(fmt, from_=5, to=120, textvariable=self.fields["timeout_seconds"], width=5)
        timeout.pack(side="left", padx=8)
        self.remote_widgets += [combo, timeout]
        for i, (var, text) in enumerate(((self.send_reference, "Stimmprobe der Figur mitsenden (Voice-Cloning)"),
                                         (self.send_language, "Sprache mitsenden"),
                                         (self.dump_references, "Stimmproben als WAV speichern (remote-voices)"))):
            box = ttk.Checkbutton(rem, text=text, variable=var)
            box.grid(row=6 + i, column=0, columnspan=3, sticky="w")
            self.remote_widgets.append(box)
        ttk.Label(rem, text="Zusätzliche Felder (JSON)").grid(row=9, column=0, sticky="nw", pady=2)
        self.extra = tk.Text(rem, height=3, width=40, font=("Consolas", 9))
        self.extra.grid(row=9, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=2)
        test = ttk.Button(rem, text="Verbindung testen", command=self._test)
        test.grid(row=10, column=2, sticky="e", pady=(4, 0))
        self.remote_widgets += [self.extra, test]

        buttons = ttk.Frame(body)
        buttons.grid(row=3, column=0, sticky="ew", **pad)
        self.install_button = ttk.Button(buttons, text="Installieren", command=self._install)
        self.install_button.pack(side="right")
        ttk.Button(buttons, text="Deinstallieren", command=self._uninstall).pack(side="right", padx=6)
        ttk.Button(buttons, text="Runtime-Ordner öffnen", command=self._open_runtime).pack(side="left")

        logf = ttk.LabelFrame(body, text="Protokoll", padding=4)
        logf.grid(row=4, column=0, sticky="nsew", **pad)
        body.rowconfigure(4, weight=1)
        self.log_text = tk.Text(logf, height=8, state="disabled", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

    # ---------------------------------------------------------------- state

    def _toggle(self):
        for widgets, on in ((self.low_widgets, self.lowreq.get()), (self.remote_widgets, self.remote.get())):
            for w in widgets:
                w.configure(state="normal" if on else "disabled")

    def _load_config(self, config):
        for key, var in self.fields.items():
            var.set(str(config.get(key, "")))
        self.fields["response_format"].set(config.get("response_format", "wav"))
        self.send_reference.set(bool(config.get("send_reference_audio", True)))
        self.send_language.set(bool(config.get("send_language", True)))
        self.dump_references.set(bool(config.get("dump_references", True)))
        self.voice_map = config.get("voice_map", {})
        self.pcm_rate = config.get("pcm_sample_rate", 24000)
        state = self.extra.cget("state")
        self.extra.configure(state="normal")
        self.extra.delete("1.0", "end")
        self.extra.insert("1.0", json.dumps(config.get("extra_body", {}), indent=1))
        self.extra.configure(state=state)

    def _config(self):
        try:
            extra = json.loads(self.extra.get("1.0", "end").strip() or "{}")
        except ValueError as e:
            raise PatchError("Zusätzliche Felder sind kein gültiges JSON: %s" % e)
        if not isinstance(extra, dict):
            raise PatchError("Zusätzliche Felder müssen ein JSON-Objekt sein.")
        url = self.fields["url"].get().strip()
        if not url.startswith(("http://", "https://")):
            raise PatchError("Server-URL muss mit http:// oder https:// beginnen.")
        return {
            "url": url,
            "api_key": self.fields["api_key"].get().strip(),
            "model": self.fields["model"].get().strip(),
            "voice": self.fields["voice"].get().strip() or "default",
            "response_format": self.fields["response_format"].get(),
            "pcm_sample_rate": self.pcm_rate,
            "timeout_seconds": int(self.fields["timeout_seconds"].get() or 25),
            "send_language": self.send_language.get(),
            "send_reference_audio": self.send_reference.get(),
            "reference_audio_field": self.fields["reference_audio_field"].get().strip() or "ref_audio",
            "extra_body": extra,
            "voice_map": self.voice_map,
            "dump_references": self.dump_references.get(),
        }

    def _game(self):
        return Game(self.game_dir.get().strip())

    def refresh(self):
        path = self.game_dir.get().strip()
        if not is_game_dir(path):
            self.status.set("Kein gültiger Spielordner gewählt")
            return
        try:
            game = self._game()
            status, options = game.status()
        except PatchError as e:
            self.status.set(str(e))
            return
        self.status.set("Status: " + STATUS_TEXT[status])
        if options:
            self.lowreq.set(options.get("lowreq", False))
            self.remote.set(options.get("remote", False))
            self.allow_cpu.set(options.get("allow_cpu", False))
            for key, var in self.limits.items():
                var.set(options.get(key, DEFAULTS[key]))
        if os.path.isfile(game.config):
            try:
                self._load_config(load_config(game.config))
            except (OSError, ValueError):
                pass
        self._toggle()

    # ---------------------------------------------------------------- actions

    def _browse(self):
        path = filedialog.askdirectory(title="Ordner von Scam With Your Friends wählen")
        if path:
            self.game_dir.set(os.path.normpath(path))

    def _open_runtime(self):
        try:
            os.startfile(self._game().runtime)
        except (PatchError, OSError) as e:
            messagebox.showerror("Fehler", str(e))

    def _install(self):
        try:
            game = self._game()
            options = Options(lowreq=self.lowreq.get(), remote=self.remote.get(), allow_cpu=self.allow_cpu.get(),
                              **{k: v.get() for k, v in self.limits.items()})
            config = self._config() if options.remote else None
        except (PatchError, tk.TclError, ValueError) as e:
            messagebox.showerror("Eingabe prüfen", str(e))
            return
        if not (options.lowreq or options.remote):
            messagebox.showinfo("Nichts gewählt", "Bitte mindestens einen Patch aktivieren.")
            return
        self._run(lambda log: game.install(options, remote_config=config, log=log))

    def _uninstall(self):
        try:
            game = self._game()
        except PatchError as e:
            messagebox.showerror("Fehler", str(e))
            return
        if messagebox.askyesno("Deinstallieren", "Originaldateien wiederherstellen?"):
            self._run(game.uninstall)

    def _test(self):
        try:
            config = self._config()
        except (PatchError, ValueError) as e:
            messagebox.showerror("Eingabe prüfen", str(e))
            return
        self._run(lambda log: log(test_server(config)), "Teste %s …" % config["url"])

    def _run(self, job, start_message=None):
        if self.busy:
            return
        self.busy = True
        self.install_button.configure(state="disabled")
        if start_message:
            self.log(start_message)

        def worker():
            try:
                job(lambda line: self.events.put(("log", line)))
            except Exception as e:  # shown to the user, never fatal for the UI
                self.events.put(("error", str(e)))
            self.events.put(("done", None))

        threading.Thread(target=worker, daemon=True).start()

    def _pump(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self.log(value)
                elif kind == "error":
                    self.log("FEHLER: " + value)
                    messagebox.showerror("Fehler", value)
                else:
                    self.busy = False
                    self.install_button.configure(state="normal")
                    self.refresh()
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def log(self, line):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


if __name__ == "__main__":
    Installer().mainloop()
