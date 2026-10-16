import subprocess
from pathlib import Path

import numpy as np

from bitrater_90000.ffmpeg_tools import NO_WINDOW, find_ffmpeg
from bitrater_90000.mp3.bitstream import read_frames
from bitrater_90000.mp3.maindata import decode_main_data
from bitrater_90000.mp3.writer import FrameSpec, GranuleSpec, write_mp3

DATA = Path(__file__).parent / "data"


def lame_tag(path: Path) -> bytes:
    data = path.read_bytes()
    info = read_frames(path)[0]
    return data[info.offset + 4 + info.header.side_info_length + 120:][:36]


def decode(path: Path) -> np.ndarray:
    result = subprocess.run(
        [find_ffmpeg(), "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "f32le", "-"],
        capture_output=True, check=True, creationflags=NO_WINDOW,
    )
    return np.frombuffer(result.stdout, dtype=np.float32)


if __name__ == "__main__":
    source = DATA / "original_128.mp3"
    frames = read_frames(source)
    audio = [f for f in frames if not f.is_info_frame]
    decoded = decode_main_data(frames)

    specs = []
    for frame, granules in zip(audio, decoded):
        specs.append(FrameSpec(
            ms_stereo=frame.header.ms_stereo,
            granules=[[GranuleSpec(
                values=np.array(gd.values),
                global_gain=gd.info.global_gain,
                scalefac_scale=gd.info.scalefac_scale,
                preflag=gd.info.preflag,
                scalefac_long=gd.scalefac_long,
                scalefac_short=gd.scalefac_short,
                block_type=gd.info.block_type,
                mixed_block=gd.info.mixed_block,
                subblock_gain=gd.info.subblock_gain,
            ) for gd in gr] for gr in granules],
        ))

    target = DATA / "roundtrip_128.mp3"
    stats = write_mp3(target, specs, audio[0].header.sample_rate, 128, lame_tag(source))

    a, b = decode(source), decode(target)
    print(f"Written:      {stats['frames']} frames, {stats['average_kbps']:.1f} kbps average, "
          f"{stats['bumped_frames']} frames needed a higher bitrate")
    print(f"Size:         original {source.stat().st_size} B, ours {target.stat().st_size} B")
    print(f"Samples:      {len(a)} vs {len(b)}")
    if len(a) == len(b):
        print(f"Identical:    {np.array_equal(a, b)}  (max difference {np.abs(a - b).max():.2e})")