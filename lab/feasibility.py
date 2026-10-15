import subprocess
from pathlib import Path

import numpy as np

from bitrater_90000.ffmpeg_tools import NO_WINDOW, find_ffmpeg
from bitrater_90000.mp3.bitstream import read_frames
from bitrater_90000.mp3.filterbank import analyze
from bitrater_90000.mp3.maindata import decode_main_data
from bitrater_90000.mp3.quantize import snap_to_lattice, step_sizes

DATA = Path(__file__).parent / "data"
OFFSET = -528


def decode_mid_side(path: Path) -> tuple[np.ndarray, np.ndarray]:
    result = subprocess.run(
        [find_ffmpeg(), "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "f32le", "-"],
        capture_output=True, check=True, creationflags=NO_WINDOW,
    )
    stereo = np.frombuffer(result.stdout, dtype=np.float32).reshape(-1, 2).astype(np.float64)
    mid = (stereo[:, 0] + stereo[:, 1]) / np.sqrt(2)
    side = (stereo[:, 0] - stereo[:, 1]) / np.sqrt(2)
    return mid, side


def test(audio_file: Path, frames, decoded) -> None:
    mid, side = decode_mid_side(audio_file)
    coefficients = [analyze(mid, OFFSET), analyze(side, OFFSET)]
    audio_frames = [f for f in frames if not f.is_info_frame]

    total = exact = granules = granules_exact = 0
    for index, (frame, granule_pair) in enumerate(zip(audio_frames, decoded)):
        if not frame.header.ms_stereo:
            continue
        for gr in range(2):
            granule = 2 * index + gr
            for ch in range(2):
                gd = granule_pair[gr][ch]
                if gd.info.window_switching or granule >= len(coefficients[ch]):
                    continue

                steps = step_sizes(gd, frame.header.sample_rate)
                recovered = snap_to_lattice(coefficients[ch][granule], steps)
                matches = recovered == np.array(gd.values)

                total += matches.size
                exact += matches.sum()
                granules += 1
                granules_exact += matches.all()

    print(f"{audio_file.name}:")
    print(f"  coefficients recovered: {exact / total * 100:.4f}%")
    print(f"  granules 100% exact:    {granules_exact} / {granules}")


if __name__ == "__main__":
    frames = read_frames(DATA / "original_128.mp3")
    decoded = decode_main_data(frames)

    test(DATA / "original_128.mp3", frames, decoded)
    test(DATA / "fake_320.mp3", frames, decoded)