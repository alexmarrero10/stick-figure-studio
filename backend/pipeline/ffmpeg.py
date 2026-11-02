"""Thin wrappers around the ffmpeg / ffprobe executables."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def run(args: list[str]) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise FFmpegError(proc.stderr.strip() or f"ffmpeg exited with {proc.returncode}")


def duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise FFmpegError(proc.stderr.strip())
    return float(json.loads(proc.stdout)["format"]["duration"])


def to_wav(src: Path, dst: Path, rate: int = 44100) -> None:
    run(["-i", str(src), "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", str(dst)])


def concat_wavs(parts: list[Path], dst: Path) -> None:
    list_file = dst.with_suffix(".txt")
    list_file.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    run(["-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(dst)])
    list_file.unlink()


def wav_to_mp3(src: Path, dst: Path) -> None:
    run(["-i", str(src), "-c:a", "libmp3lame", "-b:a", "192k", str(dst)])
