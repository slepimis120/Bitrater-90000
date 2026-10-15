from dataclasses import dataclass
from pathlib import Path

BITRATES_KBPS = [None, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, None]
SAMPLE_RATES = [44100, 48000, 32000, None]

MODE_STEREO, MODE_JOINT, MODE_DUAL, MODE_MONO = 0, 1, 2, 3


class BitReader:
    def __init__(self, data: bytes, bit_pos: int = 0):
        self.data = data
        self.pos = bit_pos

    def read(self, n: int) -> int:
        value = 0
        for _ in range(n):
            bit = (self.data[self.pos >> 3] >> (7 - (self.pos & 7))) & 1
            value = (value << 1) | bit
            self.pos += 1
        return value


@dataclass
class FrameHeader:
    bitrate_kbps: int
    sample_rate: int
    padding: int
    has_crc: bool
    channel_mode: int
    mode_extension: int

    @property
    def channels(self) -> int:
        return 1 if self.channel_mode == MODE_MONO else 2

    @property
    def ms_stereo(self) -> bool:
        return self.channel_mode == MODE_JOINT and bool(self.mode_extension & 2)

    @property
    def intensity_stereo(self) -> bool:
        return self.channel_mode == MODE_JOINT and bool(self.mode_extension & 1)

    @property
    def length(self) -> int:
        return 144_000 * self.bitrate_kbps // self.sample_rate + self.padding

    @property
    def side_info_length(self) -> int:
        return 17 if self.channels == 1 else 32

    @property
    def main_data_length(self) -> int:
        return self.length - 4 - (2 if self.has_crc else 0) - self.side_info_length


@dataclass
class GranuleInfo:
    part2_3_length: int
    big_values: int
    global_gain: int
    scalefac_compress: int
    window_switching: bool
    block_type: int
    mixed_block: bool
    table_select: list[int]
    subblock_gain: list[int]
    region0_count: int
    region1_count: int
    preflag: int
    scalefac_scale: int
    count1table_select: int


@dataclass
class Frame:
    offset: int
    header: FrameHeader
    main_data_begin: int
    scfsi: list[list[int]]
    granules: list[list[GranuleInfo]]
    is_info_frame: bool
    main_data: bytes


def parse_header(b: bytes) -> FrameHeader | None:
    if len(b) < 4 or b[0] != 0xFF or (b[1] & 0xE0) != 0xE0:
        return None
    version = (b[1] >> 3) & 3
    layer = (b[1] >> 1) & 3
    if version != 3 or layer != 1:
        return None
    bitrate = BITRATES_KBPS[b[2] >> 4]
    sample_rate = SAMPLE_RATES[(b[2] >> 2) & 3]
    if bitrate is None or sample_rate is None:
        return None
    return FrameHeader(
        bitrate_kbps=bitrate,
        sample_rate=sample_rate,
        padding=(b[2] >> 1) & 1,
        has_crc=not (b[1] & 1),
        channel_mode=b[3] >> 6,
        mode_extension=(b[3] >> 4) & 3,
    )


def _read_granule(r: BitReader) -> GranuleInfo:
    part2_3_length = r.read(12)
    big_values = r.read(9)
    global_gain = r.read(8)
    scalefac_compress = r.read(4)
    window_switching = bool(r.read(1))

    if window_switching:
        block_type = r.read(2)
        mixed_block = bool(r.read(1))
        table_select = [r.read(5), r.read(5), 0]
        subblock_gain = [r.read(3) for _ in range(3)]
        region0_count = 8 if block_type == 2 and not mixed_block else 7
        region1_count = 36
    else:
        block_type = 0
        mixed_block = False
        table_select = [r.read(5) for _ in range(3)]
        subblock_gain = [0, 0, 0]
        region0_count = r.read(4)
        region1_count = r.read(3)

    return GranuleInfo(
        part2_3_length=part2_3_length,
        big_values=big_values,
        global_gain=global_gain,
        scalefac_compress=scalefac_compress,
        window_switching=window_switching,
        block_type=block_type,
        mixed_block=mixed_block,
        table_select=table_select,
        subblock_gain=subblock_gain,
        region0_count=region0_count,
        region1_count=region1_count,
        preflag=r.read(1),
        scalefac_scale=r.read(1),
        count1table_select=r.read(1),
    )


def _parse_frame(data: bytes, offset: int, header: FrameHeader) -> Frame:
    side_start = offset + 4 + (2 if header.has_crc else 0)
    r = BitReader(data, side_start * 8)
    nch = header.channels

    main_data_begin = r.read(9)
    r.read(5 if nch == 1 else 3)
    scfsi = [[r.read(1) for _ in range(4)] for _ in range(nch)]
    granules = [[_read_granule(r) for _ in range(nch)] for _ in range(2)]

    tag_start = side_start + header.side_info_length
    tag = data[tag_start:tag_start + 4]
    return Frame(
        offset=offset,
        header=header,
        main_data_begin=main_data_begin,
        scfsi=scfsi,
        granules=granules,
        is_info_frame=tag in (b"Xing", b"Info"),
        main_data=data[tag_start:offset + header.length],
    )


def _skip_id3v2(data: bytes) -> int:
    if data[:3] != b"ID3":
        return 0
    size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
    footer = 10 if data[5] & 0x10 else 0
    return 10 + size + footer


def read_frames(path: Path) -> list[Frame]:
    data = Path(path).read_bytes()
    pos = _skip_id3v2(data)

    while pos < len(data) and parse_header(data[pos:pos + 4]) is None:
        pos += 1

    frames = []
    while (header := parse_header(data[pos:pos + 4])) is not None:
        if pos + header.length > len(data):
            break
        frames.append(_parse_frame(data, pos, header))
        pos += header.length
    return frames


def check_reservoir(frames: list[Frame]) -> int:
    errors = 0
    stream_end = 0
    used_end = 0
    for frame in frames:
        if frame.is_info_frame:
            continue
        start = stream_end - frame.main_data_begin
        bits = sum(g.part2_3_length for gr in frame.granules for g in gr)
        stream_end += frame.header.main_data_length
        end = start + (bits + 7) // 8
        if start < used_end or end > stream_end:
            errors += 1
        used_end = start + bits / 8
    return errors


if __name__ == "__main__":
    import sys
    from collections import Counter

    frames = read_frames(Path(sys.argv[1]))
    audio = [f for f in frames if not f.is_info_frame]
    grans = [g for f in audio for gr in f.granules for g in gr]

    print(f"Frames:        {len(frames)} ({len(frames) - len(audio)} Xing/Info)")
    print(f"Bitrates:      {dict(Counter(f.header.bitrate_kbps for f in audio))}")
    print(f"Stereo:        {sum(f.header.ms_stereo for f in audio)} MS, "
          f"{sum(f.header.intensity_stereo for f in audio)} intensity, "
          f"{sum(f.header.channel_mode == MODE_STEREO for f in audio)} plain stereo")
    print(f"Block types:   {dict(Counter(g.block_type for g in grans))}")
    print(f"Global gain:   {min(g.global_gain for g in grans)}..{max(g.global_gain for g in grans)}")
    print(f"Reservoir:     max main_data_begin = {max(f.main_data_begin for f in audio)} bytes")
    print(f"Consistency:   {check_reservoir(frames)} errors")