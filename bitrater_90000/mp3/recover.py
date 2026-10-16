from dataclasses import dataclass

import numpy as np

from bitrater_90000.mp3.bitstream import Frame
from bitrater_90000.mp3.maindata import GranuleData
from bitrater_90000.mp3.quantize import dequantize, snap_to_lattice, step_sizes
from bitrater_90000.mp3.tables import SFB_LONG

SQRT2 = np.sqrt(2)

TOLERANCE = 0.55
MAX_OUTLIERS = 2
MIN_RATIO = 4
SEARCH_DEPTH = 64
CLEAN_FIT = 0.8


@dataclass
class RecoveredChannel:
    values: np.ndarray
    band_k: list[int | None]
    failed_bands: int


def _band_candidates(x: np.ndarray, half_width: np.ndarray, k_min: int,
                     max_outliers: int) -> tuple[np.ndarray, np.ndarray] | None:
    if np.all(np.abs(x) <= half_width):
        return None

    k_top = int(np.ceil(4 * np.log2(np.abs(x).max()))) + 1
    ks = np.arange(k_top, k_top - SEARCH_DEPTH, -1)
    ks = ks[ks >= k_min]

    steps = 2.0 ** (ks / 4)
    a = np.abs(x)[None, :] / steps[:, None]
    low = np.floor(a ** 0.75)
    n = np.where(np.abs(low ** (4 / 3) - a) <= np.abs((low + 1) ** (4 / 3) - a), low, low + 1)

    outside = np.abs(a - n ** (4 / 3)) * steps[:, None] > half_width[None, :]
    outliers = outside.sum(axis=1)
    valid = (outliers <= max_outliers) & (n.max(axis=1) > 0)
    return ks[valid], outliers[valid]


def _estimate_channel(x: np.ndarray, half_width: np.ndarray, k320: np.ndarray,
                      bounds: list[int]) -> list:
    candidates, finest = [], []
    for b in range(22):
        lo, hi = bounds[b], bounds[b + 1]
        finest.append(int(k320[lo]) + MIN_RATIO)
        for allowed in range(MAX_OUTLIERS + 1):
            c = _band_candidates(x[lo:hi], half_width[lo:hi], finest[b], allowed)
            if c is None or len(c[0]):
                break
        candidates.append(c)

    best_cost, best = None, None
    for parity in (0, 1):
        cost, chosen = 0, []
        for c, fallback in zip(candidates, finest):
            if c is None:
                chosen.append(None)
                continue
            ks, outliers = c
            if len(ks) == 0:
                chosen.append(("fail", fallback))
                cost += 1000
                continue
            match = ks % 2 == parity
            if not match.any():
                chosen.append(int(ks[0]))
                cost += 100
                continue
            first = np.nonzero(match)[0][0]
            chosen.append(int(ks[first]))
            cost += int(outliers[first])
        if best_cost is None or cost < best_cost:
            best_cost, best = cost, chosen
    return best


def _recover_channel(x: np.ndarray, half_width: np.ndarray, k320: np.ndarray,
                     bounds: list[int]) -> RecoveredChannel:
    band_k = _estimate_channel(x, half_width, k320, bounds)
    values = np.zeros(576)
    failed = 0
    for b, k in enumerate(band_k):
        if isinstance(k, tuple):
            failed += 1
            k = band_k[b] = k[1]
        if k is not None:
            lo, hi = bounds[b], bounds[b + 1]
            values[lo:hi] = snap_to_lattice(x[lo:hi], 2.0 ** (k / 4))
    return RecoveredChannel(values=values, band_k=band_k, failed_bands=failed)


def _prepare(g0: GranuleData, g1: GranuleData, ms_stereo: bool, sample_rate: int):
    s0, s1 = step_sizes(g0, sample_rate), step_sizes(g1, sample_rate)
    q0, q1 = np.array(g0.values, float), np.array(g1.values, float)
    x0, x1 = dequantize(q0, s0), dequantize(q1, s1)

    hw0 = TOLERANCE * (4 / 3) * np.cbrt(np.maximum(np.abs(q0), 1)) * s0
    hw1 = TOLERANCE * (4 / 3) * np.cbrt(np.maximum(np.abs(q1), 1)) * s1
    k0 = np.round(4 * np.log2(s0)).astype(int)
    k1 = np.round(4 * np.log2(s1)).astype(int)

    if not ms_stereo:
        x0, x1 = (x0 + x1) / SQRT2, (x0 - x1) / SQRT2
        hw0 = hw1 = (hw0 + hw1) / SQRT2
        k0 = k1 = np.minimum(k0, k1)

    return (x0, hw0, k0), (x1, hw1, k1)


def recover_granule(g0: GranuleData, g1: GranuleData, ms_stereo: bool,
                    sample_rate: int) -> tuple[RecoveredChannel, RecoveredChannel] | None:
    if g0.info.window_switching or g1.info.window_switching:
        return None
    
    bounds = SFB_LONG[sample_rate]
    mid, side = _prepare(g0, g1, ms_stereo, sample_rate)
    return _recover_channel(*mid, bounds), _recover_channel(*side, bounds)


def recover(frames: list[Frame], decoded: list) -> list:
    audio = [f for f in frames if not f.is_info_frame]
    result = []
    for frame, granules in zip(audio, decoded):
        if granules is None or frame.header.channels != 2:
            result.append(None)
            continue
        result.append([
            recover_granule(g0, g1, frame.header.ms_stereo, frame.header.sample_rate)
            for g0, g1 in granules
        ])
    return result


def fit_quality(frames: list[Frame], decoded: list) -> float:
    audio = [f for f in frames if not f.is_info_frame]
    clean = total = 0
    for frame, granules in zip(audio, decoded):
        if granules is None or frame.header.channels != 2:
            continue
        bounds = SFB_LONG[frame.header.sample_rate]
        for g0, g1 in granules:
            if g0.info.window_switching or g1.info.window_switching:
                continue
            for x, half_width, k320 in _prepare(g0, g1, frame.header.ms_stereo,
                                                frame.header.sample_rate):
                parities = []
                for b in range(21):
                    lo, hi = bounds[b], bounds[b + 1]
                    c = _band_candidates(x[lo:hi], half_width[lo:hi],
                                         int(k320[lo]) + MIN_RATIO, 0)
                    if c is None:
                        continue
                    total += 1
                    if len(c[0]):
                        parities.append(int(c[0][0]) % 2)
                if parities:
                    clean += max(parities.count(0), parities.count(1))
    return clean / total if total else 0.0