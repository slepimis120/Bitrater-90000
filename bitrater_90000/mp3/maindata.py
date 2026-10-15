from dataclasses import dataclass

from bitrater_90000.mp3.bitstream import BitReader, Frame, GranuleInfo
from bitrater_90000.mp3.tables import (
    BIG_VALUE_CODES, COUNT1_CODES, SFB_LONG, SLEN, TABLE_SELECT,
)

_BIG_DECODE = {
    table: {(length, code): xy for xy, (code, length) in codes.items()}
    for table, codes in BIG_VALUE_CODES.items()
}
_COUNT1_DECODE = [
    {(length, code): vwxy for vwxy, (code, length) in codes.items()}
    for codes in COUNT1_CODES
]

_SCFSI_GROUPS = [(0, 6), (6, 11), (11, 16), (16, 21)]


@dataclass
class GranuleData:
    info: GranuleInfo
    scalefac_long: list[int]
    scalefac_short: list[list[int]]
    values: list[int]
    bits_left: int
    overread: bool


def _read_scalefactors(r: BitReader, g: GranuleInfo, scfsi: list[int], gr: int,
                       prev_long: list[int]) -> tuple[list[int], list[list[int]]]:
    slen1, slen2 = SLEN[g.scalefac_compress]
    long = [0] * 22
    short = [[0, 0, 0] for _ in range(13)]

    if g.window_switching and g.block_type == 2:
        first_short = 0
        if g.mixed_block:
            for sfb in range(8):
                long[sfb] = r.read(slen1)
            first_short = 3
        for sfb in range(first_short, 12):
            bits = slen1 if sfb < 6 else slen2
            for win in range(3):
                short[sfb][win] = r.read(bits)
    else:
        for group, (lo, hi) in enumerate(_SCFSI_GROUPS):
            bits = slen1 if group < 2 else slen2
            for sfb in range(lo, hi):
                long[sfb] = prev_long[sfb] if gr == 1 and scfsi[group] else r.read(bits)

    return long, short


def _read_code(r: BitReader, table: dict):
    code = length = 0
    while True:
        code = (code << 1) | r.read(1)
        length += 1
        value = table.get((length, code))
        if value is not None:
            return value
        if length > 19:
            raise ValueError("Invalid Huffman code")


def _read_big_value(r: BitReader, value: int, linbits: int) -> int:
    if linbits and value == 15:
        value += r.read(linbits)
    if value and r.read(1):
        value = -value
    return value


def _read_huffman(r: BitReader, g: GranuleInfo, end: int, sample_rate: int):
    values = [0] * 576

    if g.window_switching:
        region1, region2 = 36, 576
    else:
        bounds = SFB_LONG[sample_rate]
        region1 = bounds[g.region0_count + 1]
        region2 = bounds[min(g.region0_count + g.region1_count + 2, 22)]

    i = 0
    big_end = min(g.big_values * 2, 576)
    while i < big_end:
        region = 0 if i < region1 else 1 if i < region2 else 2
        base, linbits = TABLE_SELECT[g.table_select[region]]
        if base is not None:
            x, y = _read_code(r, _BIG_DECODE[base])
            values[i] = _read_big_value(r, x, linbits)
            values[i + 1] = _read_big_value(r, y, linbits)
        i += 2

    table = _COUNT1_DECODE[g.count1table_select]
    overread = False
    while i + 4 <= 576 and r.pos < end:
        vwxy = _read_code(r, table)
        quad = [(vwxy >> shift) & 1 for shift in (3, 2, 1, 0)]
        quad = [-q if q and r.read(1) else q for q in quad]
        if r.pos > end:
            overread = True
            break
        values[i:i + 4] = quad
        i += 4

    return values, overread


def decode_main_data(frames: list[Frame]) -> list[list[list[GranuleData]]]:
    reservoir = bytearray()
    decoded = []

    for frame in frames:
        if frame.is_info_frame:
            continue

        start = len(reservoir) - frame.main_data_begin
        reservoir += frame.main_data
        if start < 0:
            decoded.append(None)
            continue

        r = BitReader(reservoir, start * 8)
        sample_rate = frame.header.sample_rate
        granules = []
        prev_long = [[0] * 22 for _ in range(frame.header.channels)]

        for gr in range(2):
            channels = []
            for ch in range(frame.header.channels):
                g = frame.granules[gr][ch]
                end = r.pos + g.part2_3_length

                long, short = _read_scalefactors(r, g, frame.scfsi[ch], gr, prev_long[ch])
                prev_long[ch] = long
                values, overread = _read_huffman(r, g, end, sample_rate)

                channels.append(GranuleData(
                    info=g,
                    scalefac_long=long,
                    scalefac_short=short,
                    values=values,
                    bits_left=end - r.pos,
                    overread=overread,
                ))
                r.pos = end
            granules.append(channels)
        decoded.append(granules)

    return decoded


if __name__ == "__main__":
    import sys
    import time
    from pathlib import Path

    from bitrater_90000.mp3.bitstream import read_frames

    t = time.perf_counter()
    frames = read_frames(Path(sys.argv[1]))
    decoded = decode_main_data(frames)
    elapsed = time.perf_counter() - t

    grans = [g for f in decoded if f for gr in f for g in gr]
    exact = sum(g.bits_left == 0 and not g.overread for g in grans)
    last_nonzero = [max((i for i, v in enumerate(g.values) if v), default=0)
                    for g in grans if g.info.block_type != 2]

    print(f"Granules:      {len(grans)} ({sum(f is None for f in decoded)} frames skipped)")
    print(f"Exact length:  {exact} / {len(grans)}")
    print(f"Bits left:     {sum(g.bits_left > 0 for g in grans)} granules")
    print(f"Overread:      {sum(g.overread for g in grans)} granules")
    print(f"Max |value|:   {max(abs(v) for g in grans for v in g.values)}")
    print(f"Highest coef:  {max(last_nonzero)} (long blocks) "
          f"(~{max(last_nonzero) * frames[0].header.sample_rate / 2 / 576 / 1000:.1f} kHz)")
    print(f"Time:          {elapsed:.1f} s")