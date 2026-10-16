import subprocess
import time
from pathlib import Path

import numpy as np

from bitrater_90000.ffmpeg_tools import NO_WINDOW, find_ffmpeg
from bitrater_90000.mp3.reconstruct import reconstruct
from lab.writer_test import decode

DATA = Path(__file__).parent / "data"


def snr_db(reference: np.ndarray, test: np.ndarray) -> float:
    noise = np.sum((reference - test) ** 2)
    if noise == 0:
        return float("inf")
    return 10 * np.log10(np.sum(reference ** 2) / noise)


def report(name: str, reference: np.ndarray, path: Path) -> None:
    audio = decode(path)
    n = min(len(reference), len(audio))
    identical = np.mean(reference[:n] == audio[:n]) * 100
    kb = path.stat().st_size / 1024
    print(f"  {name:22} {kb:7.0f} KB   SNR vs original {snr_db(reference[:n], audio[:n]):6.1f} dB"
          f"   identical samples {identical:5.1f}%")


if __name__ == "__main__":
    original, fake = DATA / "original_128.mp3", DATA / "fake_320.mp3"
    rebuilt, reencoded = DATA / "rebuilt_128.mp3", DATA / "reencoded_128.mp3"

    start = time.perf_counter()
    stats = reconstruct(fake, rebuilt, 128)
    elapsed = time.perf_counter() - start

    subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-i", str(fake), "-map", "0:a",
                    "-c:a", "libmp3lame", "-b:a", "128k", str(reencoded)],
                   check=True, creationflags=NO_WINDOW)

    print(f"Frames:            {stats.frames} ({stats.recovered_frames} recovered, "
          f"{stats.copied_frames} copied from the upscaled file)")
    print(f"Failed bands:      {stats.failed_bands}")
    print(f"Requantized bands: {stats.requantized_bands}")
    print(f"Bitrate:           {stats.average_kbps:.1f} kbps average "
          f"({stats.bumped_frames} frames above 128)")
    print(f"Time:              {elapsed:.1f} s")
    print()

    reference = decode(original)
    report("fake_320 (input)", reference, fake)
    report("normal re-encode 128", reference, reencoded)
    report("our reconstruction", reference, rebuilt)