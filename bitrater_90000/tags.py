from pathlib import Path

from mutagen.id3 import ID3, TXXX, ID3NoHeaderError

REAL_BITRATE_TAG = "BITRATER_REAL_KBPS"


def _load(path: Path) -> ID3:
    try:
        return ID3(path)
    except ID3NoHeaderError:
        return ID3()


def _save(tags: ID3, path: Path, version: tuple) -> None:
    tags.save(path, v2_version=3 if version < (2, 4, 0) else 4)


def copy_tags(source: Path, target: Path, real_kbps: int | None = None) -> None:
    tags = _load(source)
    version = tags.version
    if real_kbps:
        tags.add(TXXX(encoding=3, desc=REAL_BITRATE_TAG, text=str(real_kbps)))
    _save(tags, target, version)


def add_real_bitrate(path: Path, real_kbps: int) -> None:
    tags = _load(path)
    version = tags.version
    tags.add(TXXX(encoding=3, desc=REAL_BITRATE_TAG, text=str(real_kbps)))
    _save(tags, path, version)