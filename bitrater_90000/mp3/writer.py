from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from bitrater_90000.mp3 import huffman
from bitrater_90000.mp3.bitstream import BITRATES_KBPS, SAMPLE_RATES
from bitrater_90000.mp3.bitwriter import BitWriter
from bitrater_90000.mp3.tables import SLEN

FRAME_BITRATES = [b for b in BITRATES_KBPS if b]
MAX_MAIN_DATA_BEGIN = 511


@dataclass
class GranuleSpec:
    values: np.ndarray
    global_gain: int
    scalefac_scale: int = 0
    preflag: int = 0
    scalefac_long: list[int] = field(default_factory=lambda: [0] * 22)
    scalefac_short: list[list[int]] = field(default_factory=lambda: [[0, 0, 0] for _ in range(13)])
    block_type: int = 0                      # 0 long, 1 start, 2 short, 3 stop
    mixed_block: bool = False
    subblock_gain: list[int] = field(default_factory=lambda: [0, 0, 0])

    @property
    def window_switching(self) -> bool:
        return self.block_type != 0


@dataclass
class FrameSpec:
    ms_stereo: bool
    granules: list[list[GranuleSpec]]


@dataclass
class _EncodedGranule:
    spec: GranuleSpec
    plan: huffman.HuffmanPlan
    scalefac_compress: int
    data: BitWriter


def _scalefactor_groups(spec: GranuleSpec) -> tuple[list[int], list[int]]:
    if spec.block_type == 2:
        short = spec.scalefac_short
        if spec.mixed_block:
            first = spec.scalefac_long[:8] + [v for sfb in range(3, 6) for v in short[sfb]]
        else:
            first = [v for sfb in range(0, 6) for v in short[sfb]]
        second = [v for sfb in range(6, 12) for v in short[sfb]]
        return first, second
    return spec.scalefac_long[:11], spec.scalefac_long[11:21]


def _choose_scalefac_compress(spec: GranuleSpec) -> int:
    first, second = _scalefactor_groups(spec)
    need1 = max(first).bit_length()
    need2 = max(second).bit_length()
    options = [(len(first) * s1 + len(second) * s2, i)
               for i, (s1, s2) in enumerate(SLEN) if s1 >= need1 and s2 >= need2]
    if not options:
        raise ValueError(f"Scalefactors too large: {max(first)}, {max(second)}")
    return min(options)[1]


def _encode_granule(spec: GranuleSpec, sample_rate: int) -> _EncodedGranule:
    compress = _choose_scalefac_compress(spec)
    slen1, slen2 = SLEN[compress]
    w = BitWriter()

    first, second = _scalefactor_groups(spec)
    for v in first:
        w.write(v, slen1)
    for v in second:
        w.write(v, slen2)

    values = np.asarray(spec.values).astype(int)
    p = huffman.plan(values, spec.window_switching, sample_rate)
    huffman.write(w, values, p, spec.window_switching, sample_rate)
    return _EncodedGranule(spec=spec, plan=p, scalefac_compress=compress, data=w)

def encoded_bits(spec: GranuleSpec, sample_rate: int) -> int:
    return _encode_granule(spec, sample_rate).data.length

def _write_side_info(w: BitWriter, main_data_begin: int, channels: int,
                     granules: list[list[_EncodedGranule]]) -> None:
    w.write(main_data_begin, 9)
    w.write(0, 5 if channels == 1 else 3)
    for _ in range(channels):
        w.write(0, 4)
    for gr in granules:
        for g in gr:
            s, p = g.spec, g.plan
            w.write(g.data.length, 12)
            w.write(p.big_values, 9)
            w.write(s.global_gain, 8)
            w.write(g.scalefac_compress, 4)
            w.write(1 if s.window_switching else 0, 1)
            if s.window_switching:
                w.write(s.block_type, 2)
                w.write(1 if s.mixed_block else 0, 1)
                w.write(p.table_select[0], 5)
                w.write(p.table_select[1], 5)
                for gain in s.subblock_gain:
                    w.write(gain, 3)
            else:
                for t in p.table_select:
                    w.write(t, 5)
                w.write(p.region0_count, 4)
                w.write(p.region1_count, 3)
            w.write(s.preflag, 1)
            w.write(s.scalefac_scale, 1)
            w.write(p.count1table_select, 1)


def _header(bitrate: int, sample_rate: int, padding: int, ms_stereo: bool) -> bytes:
    bitrate_index = BITRATES_KBPS.index(bitrate)
    rate_index = SAMPLE_RATES.index(sample_rate)
    mode, mode_extension = 1, (2 if ms_stereo else 0)
    return bytes([
        0xFF,
        0xFB,
        (bitrate_index << 4) | (rate_index << 2) | (padding << 1),
        (mode << 6) | (mode_extension << 4) | 0b0100,
    ])


def _frame_length(bitrate: int, sample_rate: int, padding: int) -> int:
    return 144_000 * bitrate // sample_rate + padding


def _crc16(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def _info_frame(frames: list[bytes], bitrate: int, sample_rate: int,
                lame_tag: bytes | None, vbr: bool) -> bytes:
    length = _frame_length(bitrate, sample_rate, 0)
    total = length + sum(len(f) for f in frames)

    offsets, position = [], length
    for f in frames:
        offsets.append(position)
        position += len(f)
    toc = bytes(min(255, 256 * offsets[i * len(frames) // 100] // total) for i in range(100))

    frame = bytearray(_header(bitrate, sample_rate, 0, False))
    frame += bytes(32)
    frame += b"Xing" if vbr else b"Info"
    frame += (15).to_bytes(4, "big")
    frame += len(frames).to_bytes(4, "big") + total.to_bytes(4, "big") + toc + bytes(4)
    if lame_tag:
        tag = bytearray(lame_tag[:36])
        tag[28:32] = total.to_bytes(4, "big")
        tag[32:34] = _crc16(b"".join(frames)).to_bytes(2, "big")
        frame += tag
        frame[190:192] = _crc16(bytes(frame[:190])).to_bytes(2, "big")
    frame += bytes(length - len(frame))
    return bytes(frame)


def write_mp3(path: Path, frames: list[FrameSpec], sample_rate: int, bitrate: int,
              lame_tag: bytes | None = None) -> dict:
    channels = len(frames[0].granules[0])
    side_info_length = 17 if channels == 1 else 32

    encoded = [[[_encode_granule(g, sample_rate) for g in gr] for gr in f.granules]
               for f in frames]

    stream = bytearray()
    used = 0
    layout = []
    remainder = 0
    bumped = 0

    for frame_granules in encoded:
        data = BitWriter()
        for gr in frame_granules:
            for g in gr:
                data.append(g.data)
        payload = data.to_bytes()

        begin = min(len(stream) - used, MAX_MAIN_DATA_BEGIN)
        used = len(stream) - begin

        for rate in [bitrate] + [b for b in FRAME_BITRATES if b > bitrate]:
            remainder_next = remainder + (144_000 * rate) % sample_rate
            padding = 1 if rate == bitrate and remainder_next >= sample_rate else 0
            slots = _frame_length(rate, sample_rate, padding) - 4 - side_info_length
            if len(payload) <= begin + slots:
                break
        else:
            raise ValueError("Frame does not fit even at 320 kbps")

        if rate == bitrate:
            remainder = remainder_next - (sample_rate if padding else 0)
        else:
            bumped += 1

        stream += bytes(slots)
        stream[used:used + len(payload)] = payload
        used += len(payload)
        layout.append((rate, padding, begin, frame_granules))

    out_frames, position = [], 0
    for (rate, padding, begin, frame_granules), spec in zip(layout, frames):
        length = _frame_length(rate, sample_rate, padding)
        slots = length - 4 - side_info_length
        side = BitWriter()
        _write_side_info(side, begin, channels, frame_granules)
        out_frames.append(_header(rate, sample_rate, padding, spec.ms_stereo)
                          + side.to_bytes() + bytes(stream[position:position + slots]))
        position += slots

    info = _info_frame(out_frames, bitrate, sample_rate, lame_tag, vbr=bumped > 0)
    Path(path).write_bytes(info + b"".join(out_frames))

    audio_bytes = sum(len(f) for f in out_frames)
    seconds = len(out_frames) * 1152 / sample_rate
    return {
        "frames": len(out_frames),
        "bumped_frames": bumped,
        "average_kbps": audio_bytes * 8 / seconds / 1000,
    }