from dataclasses import dataclass
from pathlib import Path

import numpy as np
from mutagen.mp3 import MP3

from bitrater_90000.ffmpeg_tools import DecodeError, decode_sample, decode_to_mono, find_ffmpeg

BITRATE_TABLE = [
    (19700, 320),
    (19200, 256),
    (18300, 192),
    (17200, 160),
    (15000, 128),
    (12500, 96),
    (0, 64),
]

PROFILE_PERCENTILES = (50, 75, 90)
FLOOR_DB = -120.0
CONTENT_DB = -90.0
FULL_BAND_HZ = 19_500
MAX_FRAMES = 1000
MIN_DECODABLE = 0.95


class DamagedFileError(Exception):
    pass


@dataclass
class AnalysisResult:
    claimed_kbps: int
    sample_rate: int
    cutoff_hz: float
    sharp_cutoff: bool
    cutoff_class_kbps: int | None

    @property
    def real_kbps(self) -> int | None:
        if self.cutoff_class_kbps is None:
            return None
        return min(self.cutoff_class_kbps, self.claimed_kbps)


def loud_frames_db(samples: np.ndarray, sample_rate: int, n_fft: int = 4096):
    n_frames = len(samples) // n_fft
    if n_frames == 0:
        raise ValueError("Track is too short to analyze")

    step = max(1, n_frames // MAX_FRAMES)
    frames = samples[: n_frames * n_fft].reshape(n_frames, n_fft)[::step]
    window = np.hanning(n_fft).astype(np.float32)
    power = np.abs(np.fft.rfft(frames * window, axis=1)) ** 2

    energy = power.sum(axis=1)
    loud = power[energy > np.median(energy) / 100]
    if len(loud) == 0:
        raise ValueError("Track is silent")

    freqs = np.fft.rfftfreq(n_fft, 1 / sample_rate)
    return freqs, 10 * np.log10(loud + 1e-20)


def profile_at(db: np.ndarray, percentile: int) -> np.ndarray:
    profile = np.percentile(db, percentile, axis=0)
    profile -= profile.max()
    return np.maximum(profile, FLOOR_DB)


def find_cutoff(freqs, db, min_hz=10_000, window_hz=400, min_drop_db=20.0) -> float | None:
    bin_hz = freqs[1]
    w = max(2, int(window_hz / bin_hz))
    start = max(w, int(min_hz / bin_hz))

    best_drop, best_i = 0.0, None
    for i in range(start, len(db) - w):
        left = db[i - w:i].mean()
        if left < CONTENT_DB:
            continue
        drop = left - db[i:i + w].mean()
        if drop > best_drop:
            best_drop, best_i = drop, i

    if best_i is None or best_drop < min_drop_db:
        return None
    return float(freqs[best_i])


def find_bandwidth(freqs, db) -> float:
    above = np.nonzero(db > CONTENT_DB)[0]
    return float(freqs[above[-1]]) if len(above) else 0.0


def cutoff_to_kbps(cutoff_hz: float) -> int:
    for min_cutoff, kbps in BITRATE_TABLE:
        if cutoff_hz >= min_cutoff:
            return kbps
    return BITRATE_TABLE[-1][1]


def analyze_file(path: Path, ffmpeg: str) -> AnalysisResult:
    info = MP3(path).info
    
    try:
        samples = decode_sample(path, ffmpeg, info.length)
    except DecodeError:
        samples = decode_to_mono(path, ffmpeg)
        decodable = len(samples) / info.sample_rate
        if decodable < info.length * MIN_DECODABLE:
            raise DamagedFileError(f"only {decodable:.0f} of {info.length:.0f} s can be decoded")

    freqs, db = loud_frames_db(samples, info.sample_rate)

    def result(top_hz, sharp, cutoff_class):
        return AnalysisResult(
            claimed_kbps=round(info.bitrate / 1000),
            sample_rate=info.sample_rate,
            cutoff_hz=top_hz,
            sharp_cutoff=sharp,
            cutoff_class_kbps=cutoff_class,
        )

    bandwidth = 0.0
    for percentile in PROFILE_PERCENTILES:
        profile = profile_at(db, percentile)

        cutoff = find_cutoff(freqs, profile)
        if cutoff is not None:
            return result(cutoff, True, cutoff_to_kbps(cutoff))

        bandwidth = find_bandwidth(freqs, profile)
        if bandwidth >= FULL_BAND_HZ:
            return result(bandwidth, False, 320)

    return result(bandwidth, False, None)


if __name__ == "__main__":
    import sys
    result = analyze_file(Path(sys.argv[1]), find_ffmpeg())
    print(result)
    print(f"Real bitrate: {result.real_kbps} kbps")