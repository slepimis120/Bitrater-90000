from dataclasses import dataclass
from pathlib import Path

import numpy as np

from bitrater_90000.mp3.bitstream import read_frames
from bitrater_90000.mp3.maindata import GranuleData, decode_main_data
from bitrater_90000.mp3.params import granule_params
from bitrater_90000.mp3.recover import fit_quality, recover
from bitrater_90000.mp3.writer import FrameSpec, GranuleSpec, encoded_bits, write_mp3

MAX_COPIED_GRANULE_BITS = 1200
MAX_GRANULE_BITS = 2000


@dataclass
class ReconstructionStats:
    frames: int
    recovered_frames: int
    copied_frames: int
    failed_bands: int
    requantized_bands: int
    shrunk_granules: int
    bumped_frames: int
    average_kbps: float


def read_lame_tag(path: Path) -> bytes:
    data = Path(path).read_bytes()
    first = read_frames(path)[0]
    if not first.is_info_frame:
        return b""
    return data[first.offset + 4 + first.header.side_info_length + 120:][:36]


def spec_from_granule(gd: GranuleData) -> GranuleSpec:
    return GranuleSpec(
        values=np.array(gd.values),
        global_gain=gd.info.global_gain,
        scalefac_scale=gd.info.scalefac_scale,
        preflag=gd.info.preflag,
        scalefac_long=gd.scalefac_long,
        scalefac_short=gd.scalefac_short,
        block_type=gd.info.block_type,
        mixed_block=gd.info.mixed_block,
        subblock_gain=gd.info.subblock_gain,
    )


def shrink(spec: GranuleSpec, sample_rate: int, max_bits: int) -> GranuleSpec:
    original = np.asarray(spec.values, dtype=float)
    magnitude = np.abs(original) ** (4 / 3)
    for extra in range(0, 256 - spec.global_gain):
        a = magnitude / 2 ** (extra / 4)
        low = np.floor(a ** 0.75)
        q = np.where(np.abs(low ** (4 / 3) - a) <= np.abs((low + 1) ** (4 / 3) - a), low, low + 1)
        candidate = GranuleSpec(**{**spec.__dict__,
                                   "values": (np.sign(original) * q).astype(int),
                                   "global_gain": spec.global_gain + extra})
        if encoded_bits(candidate, sample_rate) <= max_bits:
            return candidate
    return candidate


def recoverability(source: Path, max_frames: int = 1500) -> float:
    frames = read_frames(source)[: max_frames + 1]
    return fit_quality(frames, decode_main_data(frames))


def reconstruct(source: Path, target: Path, bitrate: int) -> ReconstructionStats:
    frames = read_frames(source)
    audio = [f for f in frames if not f.is_info_frame]
    decoded = decode_main_data(frames)
    recovered = recover(frames, decoded)
    sample_rate = audio[0].header.sample_rate

    specs = []
    copied = failed = requantized = shrunk = 0
    for frame, granules, rec in zip(audio, decoded, recovered):
        usable = rec is not None and all(pair is not None for pair in rec)
        if usable:
            failed += sum(ch.failed_bands for pair in rec for ch in pair)
            params = [[granule_params(ch, sample_rate) for ch in pair] for pair in rec]
            requantized += sum(p.requantized_bands for pair in params for p in pair)
            granule_specs = []
            for pair in params:
                channel_specs = []
                for p in pair:
                    spec = p.spec
                    if encoded_bits(spec, sample_rate) > MAX_GRANULE_BITS:
                        spec = shrink(spec, sample_rate, MAX_GRANULE_BITS)
                        shrunk += 1
                    channel_specs.append(spec)
                granule_specs.append(channel_specs)
            specs.append(FrameSpec(ms_stereo=True, granules=granule_specs))
        else:
            copied += 1
            specs.append(FrameSpec(
                ms_stereo=frame.header.ms_stereo,
                granules=[[shrink(spec_from_granule(gd), sample_rate, MAX_COPIED_GRANULE_BITS)
                           for gd in gr] for gr in granules],
            ))

    stats = write_mp3(target, specs, sample_rate, bitrate, read_lame_tag(source))
    return ReconstructionStats(
        frames=len(specs),
        recovered_frames=len(specs) - copied,
        copied_frames=copied,
        failed_bands=failed,
        requantized_bands=requantized,
        shrunk_granules=shrunk,
        bumped_frames=stats["bumped_frames"],
        average_kbps=stats["average_kbps"],
    )