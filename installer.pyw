"""Graphical installer for the Qwen3-TTS and Gladia speech recognition patches (Scam With Your Friends)."""
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
from qwen_patcher.paths import EXAMPLE_CONFIG, STT_EXAMPLE_CONFIG  # noqa: E402
from qwen_patcher.remote import test_server  # noqa: E402
from qwen_patcher.stt import SttGame, SttOptions, test_key  # noqa: E402

STATUS_TEXT = {
    "original": "Not patched",
    "patched": "Patched",
    "reverted": "Patch was removed by a game update – please install again",
}


class Installer(tk.Tk):
    def __init__(self):
        tk.Tk.__init__(self)
        self.title("Scam With Your Friends – Qwen3 TTS Patch %s" % VERSION)
        self.minsize(640, 780)
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
        self.gladia = tk.BooleanVar(value=False)
        self.gladia_fields = {k: tk.StringVar() for k in ("api_key", "mode", "language")}
        self.gladia_partials = tk.BooleanVar(value=False)
        self.stt_status = tk.StringVar(value="")

        self._build()
        self._load_config(load_config(EXAMPLE_CONFIG))
        self._load_stt_config(load_config(STT_EXAMPLE_CONFIG))
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

        game = ttk.LabelFrame(body, text="Game folder", padding=8)
        game.grid(row=0, column=0, sticky="ew", **pad)
        game.columnconfigure(0, weight=1)
        self.game_combo = ttk.Combobox(game, textvariable=self.game_dir)
        self.game_combo.grid(row=0, column=0, sticky="ew")
        ttk.Button(game, text="Browse…", command=self._browse).grid(row=0, column=1, padx=(6, 0))
        ttk.Label(game, textvariable=self.status, foreground="#555").grid(row=1, column=0, columnspan=2, sticky="w",
                                                                          pady=(4, 0))

        low = ttk.LabelFrame(body, text="Patch 1 – Lower the hardware requirements", padding=8)
        low.grid(row=1, column=0, sticky="ew", **pad)
        ttk.Checkbutton(low, text="Enable", variable=self.lowreq, command=self._toggle).grid(
            row=0, column=0, columnspan=4, sticky="w")
        self.low_widgets = []
        labels = (("vram", "Min. VRAM (MiB)", 0, 65536), ("ram", "Min. RAM (MiB)", 0, 262144),
                  ("avail", "Min. free RAM (MiB)", 0, 262144), ("threads", "Min. CPU threads", 0, 8))
        for i, (key, text, lo, hi) in enumerate(labels):
            r, c = 1 + i // 2, (i % 2) * 2
            ttk.Label(low, text="%s, orig. %d" % (text, ORIGINAL[key])).grid(row=r, column=c, sticky="w", pady=2)
            spin = ttk.Spinbox(low, from_=lo, to=hi, increment=1 if key == "threads" else 256,
                               textvariable=self.limits[key], width=8)
            spin.grid(row=r, column=c + 1, sticky="w", padx=(6, 24))
            self.low_widgets.append(spin)
        cpu = ttk.Checkbutton(low, text="Allow CPU without a suitable GPU (usually too slow)",
                              variable=self.allow_cpu)
        cpu.grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))
        self.low_widgets.append(cpu)

        rem = ttk.LabelFrame(body, text="Patch 2 – Offload TTS to a server on your network (OpenAI /v1/audio/speech)",
                             padding=8)
        rem.grid(row=2, column=0, sticky="ew", **pad)
        rem.columnconfigure(1, weight=1)
        ttk.Checkbutton(rem, text="Enable", variable=self.remote, command=self._toggle).grid(
            row=0, column=0, columnspan=3, sticky="w")
        self.remote_widgets = []
        rows = (("url", "Server URL"), ("api_key", "API key (optional)"), ("model", "Model"),
                ("voice", "Voice (fallback)"))
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
        for i, (var, text) in enumerate(((self.send_reference, "Send voice sample (voice cloning)"),
                                         (self.send_language, "Send language"),
                                         (self.dump_references, "Save voice samples as WAV (remote-voices)"))):
            box = ttk.Checkbutton(rem, text=text, variable=var)
            box.grid(row=6 + i, column=0, columnspan=3, sticky="w")
            self.remote_widgets.append(box)
        ttk.Label(rem, text="Extra fields (JSON)").grid(row=9, column=0, sticky="nw", pady=2)
        self.extra = tk.Text(rem, height=3, width=40, font=("Consolas", 9))
        self.extra.grid(row=9, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=2)
        test = ttk.Button(rem, text="Test connection", command=self._test)
        test.grid(row=10, column=2, sticky="e", pady=(4, 0))
        self.remote_widgets += [self.extra, test]

        stt = ttk.LabelFrame(body, text="Patch 3 – Speech recognition through Gladia (your own API key)", padding=8)
        stt.grid(row=3, column=0, sticky="ew", **pad)
        stt.columnconfigure(1, weight=1)
        ttk.Checkbutton(stt, text="Enable", variable=self.gladia, command=self._toggle).grid(
            row=0, column=0, sticky="w")
        ttk.Label(stt, textvariable=self.stt_status, foreground="#555").grid(row=0, column=1, columnspan=2, sticky="w")
        self.stt_widgets = []
        ttk.Label(stt, text="Gladia API key").grid(row=1, column=0, sticky="w", pady=2)
        key = ttk.Entry(stt, textvariable=self.gladia_fields["api_key"], show="•")
        key.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(6, 0))
        ttk.Label(stt, text="Mode / Language").grid(row=2, column=0, sticky="w", pady=2)
        row = ttk.Frame(stt)
        row.grid(row=2, column=1, columnspan=2, sticky="w", padx=(6, 0))
        mode = ttk.Combobox(row, textvariable=self.gladia_fields["mode"], values=("prerecorded", "live"),
                            state="readonly", width=12)
        mode.pack(side="left")
        lang = ttk.Entry(row, textvariable=self.gladia_fields["language"], width=8)
        lang.pack(side="left", padx=8)
        ttk.Label(row, text="empty = the game's call language, auto = detect", foreground="#555").pack(side="left")
        partials = ttk.Checkbutton(stt, text="Partial transcripts while speaking (sends audio repeatedly, costs more)",
                                   variable=self.gladia_partials)
        partials.grid(row=3, column=0, columnspan=3, sticky="w")
        test_stt = ttk.Button(stt, text="Test API key", command=self._test_key)
        test_stt.grid(row=4, column=2, sticky="e", pady=(4, 0))
        self.stt_widgets += [key, mode, lang, partials, test_stt]

        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, sticky="ew", **pad)
        self.install_button = ttk.Button(buttons, text="Install", command=self._install)
        self.install_button.pack(side="right")
        ttk.Button(buttons, text="Uninstall", command=self._uninstall).pack(side="right", padx=6)
        ttk.Button(buttons, text="Open runtime folder", command=self._open_runtime).pack(side="left")

        logf = ttk.LabelFrame(body, text="Log", padding=4)
        logf.grid(row=5, column=0, sticky="nsew", **pad)
        body.rowconfigure(5, weight=1)
        self.log_text = tk.Text(logf, height=8, state="disabled", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

    # ---------------------------------------------------------------- state

    def _toggle(self):
        for widgets, on in ((self.low_widgets, self.lowreq.get()), (self.remote_widgets, self.remote.get()),
                            (self.stt_widgets, self.gladia.get())):
            for w in widgets:
                w.configure(state="normal" if on else "disabled")

    def _load_config(self, config):
        self.loaded_config = dict(config)  # keeps settings the form does not show
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
            raise PatchError("Extra fields are not valid JSON: %s" % e)
        if not isinstance(extra, dict):
            raise PatchError("Extra fields must be a JSON object.")
        url = self.fields["url"].get().strip()
        if not url.startswith(("http://", "https://")):
            raise PatchError("The server URL must start with http:// or https://.")
        config = dict(self.loaded_config)
        config.update({
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
        })
        return config

    def _load_stt_config(self, config):
        self.loaded_stt_config = dict(config)
        for key, var in self.gladia_fields.items():
            var.set(str(config.get(key, "")))
        self.gladia_fields["mode"].set(config.get("mode") or "prerecorded")

    def _stt_config(self):
        config = dict(self.loaded_stt_config)
        key = self.gladia_fields["api_key"].get().strip()
        if not key:
            raise PatchError("Please enter your Gladia API key (app.gladia.io, API keys).")
        config.update({"api_key": key, "mode": self.gladia_fields["mode"].get() or "prerecorded",
                       "language": self.gladia_fields["language"].get().strip().lower()})
        return config

    def _game(self):
        return Game(self.game_dir.get().strip())

    def _stt_game(self):
        return SttGame(self.game_dir.get().strip())

    def refresh(self):
        path = self.game_dir.get().strip()
        if not is_game_dir(path):
            self.status.set("No valid game folder selected")
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
        try:
            stt = self._stt_game()
            stt_status, stt_options = stt.status()
            self.stt_status.set("Status: " + STATUS_TEXT[stt_status])
            if stt_options is not None:
                self.gladia.set(True)
                self.gladia_partials.set(stt_options.get("partials", False))
            if os.path.isfile(stt.config):
                self._load_stt_config(load_config(stt.config))
        except (PatchError, OSError, ValueError) as e:
            self.stt_status.set(str(e))
        self._toggle()

    # ---------------------------------------------------------------- actions

    def _browse(self):
        path = filedialog.askdirectory(title="Select the Scam With Your Friends folder")
        if path:
            self.game_dir.set(os.path.normpath(path))

    def _open_runtime(self):
        try:
            only_stt = self.gladia.get() and not (self.lowreq.get() or self.remote.get())
            os.startfile(self._stt_game().runtime if only_stt else self._game().runtime)
        except (PatchError, OSError) as e:
            messagebox.showerror("Error", str(e))

    def _install(self):
        try:
            game = self._game()
            options = Options(lowreq=self.lowreq.get(), remote=self.remote.get(), allow_cpu=self.allow_cpu.get(),
                              **{k: v.get() for k, v in self.limits.items()})
            config = self._config() if options.remote else None
            gladia = self.gladia.get()
            stt = self._stt_game() if gladia else None
            stt_config = self._stt_config() if gladia else None
            stt_options = SttOptions(partials=self.gladia_partials.get())
        except (PatchError, tk.TclError, ValueError) as e:
            messagebox.showerror("Check your input", str(e))
            return
        tts = options.lowreq or options.remote
        if not (tts or gladia):
            messagebox.showinfo("Nothing selected", "Please enable at least one patch.")
            return

        def job(log):
            # Unticked patches that are currently installed are removed, so the game matches the form.
            if tts:
                game.install(options, remote_config=config, log=log)
            elif game.status()[0] != "original":
                game.uninstall(log=log)
            if gladia:
                stt.install(stt_options, stt_config, log=log)
            else:
                try:
                    current = self._stt_game()
                except PatchError:
                    return
                if current.status()[0] != "original":
                    current.uninstall(log=log)
        self._run(job)

    def _uninstall(self):
        try:
            game = self._game()
        except PatchError as e:
            messagebox.showerror("Error", str(e))
            return
        def job(log):
            game.uninstall(log=log)
            try:
                stt = self._stt_game()
            except PatchError:
                return
            stt.uninstall(log=log)
        if messagebox.askyesno("Uninstall", "Restore the original files (all patches)?"):
            self._run(job)

    def _test(self):
        try:
            config = self._config()
        except (PatchError, ValueError) as e:
            messagebox.showerror("Check your input", str(e))
            return
        self._run(lambda log: log(test_server(config)), "Testing %s …" % config["url"])

    def _test_key(self):
        try:
            config = self._stt_config()
        except PatchError as e:
            messagebox.showerror("Check your input", str(e))
            return
        self._run(lambda log: log(test_key(config)[1]), "Checking the Gladia API key …")

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
                    self.log("ERROR: " + value)
                    messagebox.showerror("Error", value)
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
