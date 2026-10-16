from dataclasses import dataclass

import numpy as np

from bitrater_90000.mp3.bitwriter import BitWriter
from bitrater_90000.mp3.tables import BIG_VALUE_CODES, COUNT1_CODES, SFB_LONG, TABLE_SELECT

INVALID = 1e7

_LENGTHS = {}
for _base, _codes in BIG_VALUE_CODES.items():
    _arr = np.full((16, 16), INVALID)
    for (_x, _y), (_, _length) in _codes.items():
        _arr[_x, _y] = _length
    _LENGTHS[_base] = _arr

_TABLE_MAX = []
for _base, _linbits in TABLE_SELECT:
    if _base is None:
        _TABLE_MAX.append(0)
    elif _linbits:
        _TABLE_MAX.append(15 + (1 << _linbits) - 1)
    else:
        _TABLE_MAX.append(max(max(x, y) for x, y in BIG_VALUE_CODES[_base]))


@dataclass
class HuffmanPlan:
    big_values: int
    count1_end: int
    table_select: list[int]
    region0_count: int
    region1_count: int
    count1table_select: int
    bits: int


def _pair_costs(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    costs = np.full((32, len(x)), INVALID)
    largest = np.maximum(x, y)
    signs = (x > 0).astype(int) + (y > 0)
    for t, (base, linbits) in enumerate(TABLE_SELECT):
        if base is None:
            costs[t] = np.where(largest == 0, 0, INVALID) if t == 0 else INVALID
            continue
        xc, yc = np.minimum(x, 15), np.minimum(y, 15)
        bits = _LENGTHS[base][xc, yc] + signs
        if linbits:
            bits = bits + linbits * ((x >= 15).astype(int) + (y >= 15))
        costs[t] = np.where(largest <= _TABLE_MAX[t], bits, INVALID)
    return costs


def _region_ends(window_switching: bool, sample_rate: int, big_end: int):
    if window_switching:
        return [(None, None, min(36, big_end), big_end)]
    bounds = SFB_LONG[sample_rate]
    options = []
    for r0 in range(16):
        for r1 in range(8):
            region1 = min(bounds[r0 + 1], big_end)
            region2 = min(bounds[min(r0 + r1 + 2, 22)], big_end)
            options.append((r0, r1, region1, region2))
    return options


def plan(values: np.ndarray, window_switching: bool, sample_rate: int) -> HuffmanPlan:
    a = np.abs(values).astype(int)

    end = 576
    while end > 0 and a[end - 1] == 0 and a[end - 2] == 0:
        end -= 2
    big_end = end
    while big_end >= 4 and a[big_end - 4:big_end].max() <= 1:
        big_end -= 4

    quads = a[big_end:end].reshape(-1, 4)
    vwxy = (quads[:, 0] << 3) | (quads[:, 1] << 2) | (quads[:, 2] << 1) | quads[:, 3]
    signs = int(quads.sum())
    count1_bits = [sum(COUNT1_CODES[t][v][1] for v in vwxy) + signs for t in (0, 1)]
    count1table = int(np.argmin(count1_bits))

    costs = _pair_costs(a[0:big_end:2], a[1:big_end:2])
    cumulative = np.concatenate([np.zeros((32, 1)), np.cumsum(costs, axis=1)], axis=1)

    def best_table(start: int, stop: int) -> tuple[int, float]:
        if start >= stop:
            return 0, 0.0
        region_cost = cumulative[:, stop // 2] - cumulative[:, start // 2]
        t = int(np.argmin(region_cost))
        return t, float(region_cost[t])

    best = None
    for r0, r1, region1, region2 in _region_ends(window_switching, sample_rate, big_end):
        t0, c0 = best_table(0, region1)
        t1, c1 = best_table(region1, region2)
        t2, c2 = best_table(region2, big_end)
        total = c0 + c1 + c2
        if best is None or total < best[0]:
            best = (total, [t0, t1, t2], r0, r1)

    total, tables, r0, r1 = best
    if window_switching:
        tables[2] = 0
    return HuffmanPlan(
        big_values=big_end // 2,
        count1_end=end,
        table_select=tables,
        region0_count=r0 if r0 is not None else 0,
        region1_count=r1 if r1 is not None else 0,
        count1table_select=count1table,
        bits=int(total) + count1_bits[count1table],
    )


def _write_value_extra(w: BitWriter, value: int, linbits: int) -> None:
    magnitude = abs(value)
    if linbits and magnitude >= 15:
        w.write(magnitude - 15, linbits)
    if magnitude:
        w.write(1 if value < 0 else 0, 1)


def write(w: BitWriter, values: np.ndarray, p: HuffmanPlan, window_switching: bool,
          sample_rate: int) -> None:
    values = values.astype(int)
    big_end = p.big_values * 2
    if window_switching:
        region1, region2 = 36, 576
    else:
        bounds = SFB_LONG[sample_rate]
        region1 = bounds[p.region0_count + 1]
        region2 = bounds[min(p.region0_count + p.region1_count + 2, 22)]

    for i in range(0, big_end, 2):
        region = 0 if i < region1 else 1 if i < region2 else 2
        base, linbits = TABLE_SELECT[p.table_select[region]]
        if base is None:
            continue
        x, y = values[i], values[i + 1]
        code, length = BIG_VALUE_CODES[base][(min(abs(x), 15), min(abs(y), 15))]
        w.write(code, length)
        _write_value_extra(w, x, linbits)
        _write_value_extra(w, y, linbits)

    table = COUNT1_CODES[p.count1table_select]
    for i in range(big_end, p.count1_end, 4):
        quad = values[i:i + 4]
        vwxy = (abs(quad[0]) << 3) | (abs(quad[1]) << 2) | (abs(quad[2]) << 1) | abs(quad[3])
        code, length = table[vwxy]
        w.write(code, length)
        for v in quad:
            if v:
                w.write(1 if v < 0 else 0, 1)