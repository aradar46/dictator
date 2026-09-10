#!/usr/bin/env python3
 
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent / "src" / "dictator"))
from transcriber import ENGINE, ENGINE_COMMIT, ENGINE_SOURCE, MODEL, MODEL_REVISION, MODEL_SHA256, ROOT


def download(url, target, checksum):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        with target.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() == checksum:
                print(f"Verified {target.name}", flush=True)
                return
    partial = target.with_suffix(target.suffix + ".part")
    try:
        digest = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as stream:
            count, reported = 0, 0
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
                digest.update(chunk)
                count += len(chunk)
                if count - reported >= 25 * 1024 * 1024:
                    print(f"{target.name}: {count // (1024 * 1024)} MiB", flush=True)
                    reported = count
        if digest.hexdigest() != checksum:
            raise RuntimeError(f"Checksum mismatch for {target.name}; not installing it")
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def main():
    for command in ("cmake", "c++", "ninja"):
        if not shutil.which(command):
            raise SystemExit(f"Install {command} before running this setup.")
    archive = ROOT / ("whisper-" + ENGINE_COMMIT + ".tar.gz")
    download("https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/" + ENGINE_COMMIT,
             archive, "f3585ebf64df3e41b26c45d93bdb38b423ca1de0bf40cc4b6d320254867a75df")
    if not ENGINE_SOURCE.exists():
        with tarfile.open(archive) as source:
            source.extractall(ROOT, filter="data")
    subprocess.run(["cmake", "-S", str(ENGINE_SOURCE), "-B", str(ENGINE_SOURCE / "build"),
                    "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=OFF",
                    "-DWHISPER_BUILD_TESTS=OFF", "-DGGML_CUDA=OFF", "-DGGML_VULKAN=OFF"], check=True)
    subprocess.run(["cmake", "--build", str(ENGINE_SOURCE / "build"),
                    "--target", "whisper-cli", "--parallel", "4"], check=True)
    download(f"https://huggingface.co/ggerganov/whisper.cpp/resolve/{MODEL_REVISION}/ggml-small-q5_1.bin",
             MODEL, MODEL_SHA256)
    print(f"Ready: {ENGINE}\nModel: {MODEL}\nLaunch: python3 dictator.py", flush=True)


if __name__ == "__main__":
    main()
