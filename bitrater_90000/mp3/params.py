from dataclasses import dataclass

import numpy as np

from bitrater_90000.mp3.quantize import dequantize, snap_to_lattice
from bitrater_90000.mp3.recover import RecoveredChannel
from bitrater_90000.mp3.tables import PRETAB, SFB_LONG
from bitrater_90000.mp3.writer import GranuleSpec

MAX_SCALEFAC = [15] * 11 + [7] * 10 + [0]


@dataclass
class ParamsResult:
    spec: GranuleSpec
    requantized_bands: int


def _try(band_k: list[int | None], gain: int, m: int, preflag: int) -> list[int] | None:
    scalefac = []
    for b, k in enumerate(band_k):
        if k is None:
            scalefac.append(0)
            continue
        diff = gain - k
        if diff % m:
            return None
        sf = diff // m - preflag * PRETAB[b]
        if sf < 0 or sf > MAX_SCALEFAC[b]:
            return None
        scalefac.append(sf)
    return scalefac


def _cost(scalefac: list[int]) -> int:
    return 11 * max(scalefac[:11]).bit_length() + 10 * max(scalefac[11:21]).bit_length()


def granule_params(channel: RecoveredChannel, sample_rate: int) -> ParamsResult:
    band_k = list(channel.band_k)
    known = [k for k in band_k if k is not None]
    if not known:
        return ParamsResult(GranuleSpec(values=np.zeros(576, int), global_gain=0), 0)

    gains = [band_k[21]] if band_k[21] is not None else [max(known) + extra for extra in range(4)]

    best = None
    for gain in gains:
        for scale, m in ((0, 2), (1, 4)):
            for preflag in (0, 1):
                scalefac = _try(band_k, gain, m, preflag)
                if scalefac is not None:
                    option = (_cost(scalefac), gain, scale, preflag, scalefac)
                    if best is None or option[0] < best[0]:
                        best = option
    values = channel.values.astype(int)
    requantized = 0

    if best is None:
        gain, m, preflag = max(known), 2, 0
        if band_k[21] is not None:
            gain = band_k[21]
        bounds = SFB_LONG[sample_rate]
        scalefac = []
        values = values.copy()
        for b, k in enumerate(band_k):
            if k is None:
                scalefac.append(0)
                continue
            sf = (gain - k) // m
            if (gain - k) % m or not 0 <= sf <= MAX_SCALEFAC[b]:
                sf = min(max(sf, 0), MAX_SCALEFAC[b])
                lo, hi = bounds[b], bounds[b + 1]
                coef = dequantize(values[lo:hi], 2.0 ** (k / 4))
                new_step = 2.0 ** ((gain - m * sf) / 4)
                values[lo:hi] = snap_to_lattice(coef, new_step).astype(int)
                requantized += 1
            scalefac.append(sf)
        best = (0, gain, 0, 0, scalefac)

    _, gain, scale, preflag, scalefac = best
    spec = GranuleSpec(
        values=values,
        global_gain=gain + 210,
        scalefac_scale=scale,
        preflag=preflag,
        scalefac_long=scalefac,
    )
    if not 0 <= spec.global_gain <= 255:
        raise ValueError(f"global_gain out of range: {spec.global_gain}")
    return ParamsResult(spec, requantized)