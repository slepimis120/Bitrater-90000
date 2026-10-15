import subprocess
import sys
from pathlib import Path

from bitrater_90000.ffmpeg_tools import find_ffmpeg

DATA = Path(__file__).parent / "data"


def encode(ffmpeg: str, src: Path, dst: Path, kbps: int, extra: list[str] = ()) -> None:
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", *extra, "-i", str(src),
         "-map", "0:a", "-c:a", "libmp3lame", "-b:a", f"{kbps}k", str(dst)],
        check=True,
    )


if __name__ == "__main__":
    source = Path(sys.argv[1])
    DATA.mkdir(exist_ok=True)
    ffmpeg = find_ffmpeg()

    original = DATA / "original_128.mp3"
    fake = DATA / "fake_320.mp3"

    encode(ffmpeg, source, original, 128, ["-ss", "30", "-t", "30"])
    encode(ffmpeg, original, fake, 320)

    for f in (original, fake):
        print(f"{f.name}: {f.stat().st_size / 1024:.0f} KB")