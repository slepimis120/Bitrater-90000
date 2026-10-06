import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SAMPLE_SEGMENTS = 8
SEGMENT_SECONDS = 12.0


def find_ffmpeg() -> str:
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    candidates = []

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys._MEIPASS) / "bin" / exe)

    candidates.append(Path(__file__).resolve().parent.parent / "bin" / exe)

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    found = shutil.which("ffmpeg")
    if found:
        return found

    raise FileNotFoundError("ffmpeg nije pronađen (ni u bin/ ni na PATH-u)")

class DecodeError(RuntimeError):
    pass


def _short_error(stderr: bytes) -> str:
    lines = stderr.decode(errors="replace").strip().splitlines()
    if not lines:
        return "ffmpeg failed"
    return lines[0].split("] ")[-1]


def _run_pcm(cmd: list[str]) -> np.ndarray:
    result = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW)
    if result.returncode != 0:
        raise DecodeError(_short_error(result.stderr))
    return np.frombuffer(result.stdout, dtype=np.float32)


def decode_to_mono(path: Path, ffmpeg: str) -> np.ndarray:
    return _run_pcm([
        ffmpeg, "-v", "error",
        "-i", str(path),
        "-map", "0:a:0",
        "-ac", "1",
        "-f", "f32le",
        "-",
    ])


def decode_sample(path: Path, ffmpeg: str, duration: float) -> np.ndarray:
    if duration <= SAMPLE_SEGMENTS * SEGMENT_SECONDS * 1.2:
        return decode_to_mono(path, ffmpeg)

    cmd = [ffmpeg, "-v", "error"]
    for i in range(SAMPLE_SEGMENTS):
        start = (duration - SEGMENT_SECONDS) * i / (SAMPLE_SEGMENTS - 1)
        cmd += ["-ss", f"{start:.2f}", "-t", str(SEGMENT_SECONDS), "-i", str(path)]

    inputs = "".join(f"[{i}:a:0]" for i in range(SAMPLE_SEGMENTS))
    cmd += [
        "-filter_complex",
        f"{inputs}concat=n={SAMPLE_SEGMENTS}:v=0:a=1,aformat=channel_layouts=mono[out]",
        "-map", "[out]",
        "-f", "f32le",
        "-",
    ]
    return _run_pcm(cmd)