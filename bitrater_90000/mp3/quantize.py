import numpy as np

from bitrater_90000.mp3.maindata import GranuleData
from bitrater_90000.mp3.tables import PRETAB, SFB_LONG


def step_sizes(gd: GranuleData, sample_rate: int) -> np.ndarray:
    g = gd.info
    bounds = SFB_LONG[sample_rate]
    multiplier = 0.5 * (1 + g.scalefac_scale)
    base = 2 ** (0.25 * (g.global_gain - 210))

    steps = np.empty(576)
    for sfb in range(22):
        scalefac = gd.scalefac_long[sfb] + g.preflag * PRETAB[sfb]
        steps[bounds[sfb]:bounds[sfb + 1]] = base * 2 ** (-multiplier * scalefac)
    return steps


def dequantize(values: np.ndarray, steps: np.ndarray) -> np.ndarray:
    return np.sign(values) * np.abs(values) ** (4 / 3) * steps


def snap_to_lattice(coef: np.ndarray, steps: np.ndarray) -> np.ndarray:
    a = np.abs(coef) / steps
    low = np.floor(a ** 0.75)
    high = low + 1
    q = np.where(np.abs(low ** (4 / 3) - a) <= np.abs(high ** (4 / 3) - a), low, high)
    return np.sign(coef) * q