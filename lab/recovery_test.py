import time
from pathlib import Path

import numpy as np

from bitrater_90000.mp3.bitstream import read_frames
from bitrater_90000.mp3.maindata import decode_main_data
from bitrater_90000.mp3.quantize import dequantize, step_sizes
from bitrater_90000.mp3.recover import RecoveredChannel, recover
from bitrater_90000.mp3.tables import SFB_LONG

DATA = Path(__file__).parent / "data"


def load(name: str):
    frames = read_frames(DATA / name)
    return frames, decode_main_data(frames)


def recovered_coefficients(channel: RecoveredChannel, sample_rate: int) -> np.ndarray:
    bounds = SFB_LONG[sample_rate]
    coef = np.zeros(576)
    for b, k in enumerate(channel.band_k):
        if k is not None:
            lo, hi = bounds[b], bounds[b + 1]
            coef[lo:hi] = dequantize(channel.values[lo:hi], 2.0 ** (k / 4))
    return coef


if __name__ == "__main__":
    original_frames, original = load("original_128.mp3")
    fake_frames, fake = load("fake_320.mp3")

    start = time.perf_counter()
    recovered = recover(fake_frames, fake)
    elapsed = time.perf_counter() - start

    original_audio = [f for f in original_frames if not f.is_info_frame]
    total = exact = granules = granules_exact = skipped = failed_bands = 0

    for frame, truth, rec in zip(original_audio, original, recovered):
        for gr in range(2):
            pair = rec[gr] if rec else None
            if pair is None:
                skipped += 1
                continue
            for ch in range(2):
                gd = truth[gr][ch]
                if gd.info.window_switching or not frame.header.ms_stereo:
                    continue

                expected = dequantize(np.array(gd.values, float),
                                      step_sizes(gd, frame.header.sample_rate))
                got = recovered_coefficients(pair[ch], frame.header.sample_rate)
                matches = np.isclose(got, expected, rtol=1e-9, atol=1e-15)

                total += matches.size
                exact += matches.sum()
                granules += 1
                granules_exact += matches.all()
                failed_bands += pair[ch].failed_bands

    print(f"Coefficients recovered: {exact / total * 100:.4f}%")
    print(f"Granules 100% exact:    {granules_exact} / {granules} ({granules_exact / granules * 100:.2f}%)")
    print(f"Failed bands:           {failed_bands}")
    print(f"Skipped granules:       {skipped} (short blocks in the upscaled file)")
    print(f"Time:                   {elapsed:.1f} s")