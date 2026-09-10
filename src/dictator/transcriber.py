import json
import os
from pathlib import Path
import tempfile
import threading
import urllib.request

from gi.repository import Gio, GLib

import shutil

ENGINE_COMMIT = "306c88f4d1286aec1bf96e544632897886af5501"  # whisper.cpp v1.9.2
MODEL_REVISION = "5359861c739e955e79d9a303bcbc70fb988958b1"
MODEL_SHA256 = "ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb"
ROOT = Path(os.path.expanduser("~/.cache/dictator"))
ENGINE_SOURCE = ROOT / ("whisper.cpp-" + ENGINE_COMMIT)


def get_engine_path():
    app_bin = Path("/app/bin/whisper-cli")
    if app_bin.is_file() and os.access(app_bin, os.X_OK):
        return app_bin
    cached = ENGINE_SOURCE / "build/bin/whisper-cli"
    if cached.is_file() and os.access(cached, os.X_OK):
        return cached
    which = shutil.which("whisper-cli")
    if which:
        return Path(which)
    return cached


ENGINE = get_engine_path()
MODEL = ROOT / "models/ggml-small-q5_1.bin"

MODELS = {
    "tiny": {"label": "Tiny", "size": "75 MB", "file": "ggml-tiny.bin"},
    "base": {"label": "Base", "size": "148 MB", "file": "ggml-base.bin"},
    "small-q5": {"label": "Small (Q5)", "size": "190 MB", "file": "ggml-small-q5_1.bin"},
    "small": {"label": "Small", "size": "488 MB", "file": "ggml-small.bin"},
    "medium": {"label": "Medium", "size": "1.5 GB", "file": "ggml-medium.bin"},
    "large-v3-turbo-q5": {"label": "Large Turbo (Q5)", "size": "574 MB", "file": "ggml-large-v3-turbo-q5_0.bin"},
    "large-v3-turbo": {"label": "Large Turbo", "size": "1.6 GB", "file": "ggml-large-v3-turbo.bin"},
}
CONFIG_FILE = ROOT / "config.json"


def get_model_path(name):
    filename = MODELS.get(name, MODELS["small-q5"])["file"]
    return ROOT / "models" / filename


def model_exists(name):
    return get_model_path(name).is_file()


def load_config():
    try:
        if CONFIG_FILE.is_file():
            return json.loads(CONFIG_FILE.read_text())
    except Exception:
        pass
    return {"model": "small-q5"}


def save_config(config):
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(config))
    except Exception:
        pass


def download_model_async(name, progress_cb, done_cb, cancel_event=None):
    filename = MODELS.get(name, MODELS["small-q5"])["file"]
    url = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{filename}"
    target = ROOT / "models" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(".part")

    def worker():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dictator"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as f:
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                while chunk := resp.read(256 * 1024):
                    if cancel_event and cancel_event.is_set():
                        part.unlink(missing_ok=True)
                        return
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total and progress_cb:
                        frac = min(1.0, downloaded / total)
                        GLib.idle_add(progress_cb, frac, downloaded, total)
            part.replace(target)
            if done_cb:
                GLib.idle_add(done_cb, True, None)
        except Exception as exc:
            part.unlink(missing_ok=True)
            if done_cb and not (cancel_event and cancel_event.is_set()):
                GLib.idle_add(done_cb, False, str(exc))

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t


class Transcriber:
    def __init__(self, model_name=None):
        self.process = None
        if not model_name:
            cfg = load_config()
            model_name = cfg.get("model", "small-q5")
        self.model_name = model_name if model_name in MODELS else "small-q5"

    def set_model(self, model_name):
        if model_name in MODELS:
            self.model_name = model_name
            cfg = load_config()
            cfg["model"] = model_name
            save_config(cfg)

    def available(self):
        engine = get_engine_path()
        return engine.is_file() and os.access(engine, os.X_OK) and model_exists(self.model_name)

    def start(self, wav_path, callback):
        engine = get_engine_path()
        if not self.available():
            raise RuntimeError(f"The speech engine or model '{self.model_name}' is missing.")
        if self.process:
            raise RuntimeError("Transcription is already running.")
        directory = tempfile.TemporaryDirectory(prefix="transcribe-", dir=ROOT)
        output = Path(directory.name) / "result"
        model_file = get_model_path(self.model_name)
        try:
            process = Gio.Subprocess.new([
                str(engine), "--model", str(model_file), "--file", str(wav_path),
                "--language", "auto", "--threads", str(min(8, os.cpu_count() or 2)),
                "--no-gpu", "--no-prints", "--suppress-nst",
                "--output-json", "--output-file", str(output),
            ], Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_PIPE)
        except GLib.Error:
            directory.cleanup()
            raise
        self.process = process

        def completed(process, result):
            text, error = None, None
            try:
                _, stdout, stderr = process.communicate_utf8_finish(result)  # Drain stderr and reap, including after cancellation.
                if self.process is not process:
                    return
                json_file = output.with_suffix(".json")
                if not json_file.is_file():
                    err = (stderr or "").strip()
                    if "failed to read" in err or "Invalid argument" in err:
                        text = ""  # Unusable / empty audio
                    else:
                        raise RuntimeError(f"Speech engine error: {err[:200] if err else 'unknown'}")
                else:
                    data = json.loads(json_file.read_text())
                    text = " ".join(segment["text"].strip() for segment in data.get("transcription", [])).strip()
            except (GLib.Error, OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                error = str(exc)
            finally:
                directory.cleanup()
            if self.process is process:
                self.process = None
                callback(text, error)

        process.communicate_utf8_async(None, None, completed)

    def cancel(self):
        process, self.process = self.process, None
        if process:
            process.force_exit()
