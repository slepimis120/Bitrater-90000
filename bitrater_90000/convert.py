import os
import shutil
import signal
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from bitrater_90000.analyzer import AnalysisResult, DamagedFileError, analyze_file
from bitrater_90000.ffmpeg_tools import NO_WINDOW
from bitrater_90000.mp3.reconstruct import reconstruct, recoverability
from bitrater_90000.mp3.recover import CLEAN_FIT
from bitrater_90000.report import FAKE_MARGIN_KBPS, find_mp3_files
from bitrater_90000.tags import add_real_bitrate, copy_tags

MODES = ("auto", "reencode", "tag")
STANDARD_BITRATES = [32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]


@dataclass
class ConvertResult:
    path: Path
    action: str
    detail: str = ""


def load_overrides(path: Path | None) -> dict[str, int]:
    overrides = {}
    if path is None:
        return overrides
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        kbps, rel = line.split(maxsplit=1)
        overrides[_key(Path(rel))] = int(kbps)
    return overrides


def _key(rel: Path) -> str:
    return os.path.normcase(str(rel))


def target_bitrate(analysis: AnalysisResult, override: int | None, step_up: bool) -> int | None:
    if override:
        return override
    real = analysis.real_kbps
    if real is None or analysis.claimed_kbps - real < FAKE_MARGIN_KBPS:
        return None
    if step_up:
        higher = [b for b in STANDARD_BITRATES if b > real]
        if higher and higher[0] < analysis.claimed_kbps:
            return higher[0]
    return real


def reencode(source: Path, target: Path, kbps: int, ffmpeg: str) -> None:
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-i", str(source), "-map", "0:a:0", "-map_metadata", "-1",
         "-c:a", "libmp3lame", "-b:a", f"{kbps}k", "-compression_level", "0", str(target)],
        check=True, capture_output=True, creationflags=NO_WINDOW,
    )


def _convert_one(source: Path, target: Path, rel: Path, ffmpeg: str, mode: str,
                 override: int | None, step_up: bool) -> ConvertResult:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        analysis = analyze_file(source, ffmpeg)
    except DamagedFileError as e:
        shutil.copy2(source, target)
        return ConvertResult(rel, "copied", f"damaged, {e}")
    except Exception as e:
        return ConvertResult(rel, "failed", f"{type(e).__name__}: {e}")

    kbps = target_bitrate(analysis, override, step_up)
    if kbps is None:
        shutil.copy2(source, target)
        return ConvertResult(rel, "copied", "uncertain" if analysis.real_kbps is None else "ok")

    temp = target.with_name(target.stem + ".bitrater-tmp.mp3")
    try:
        if mode == "tag":
            shutil.copy2(source, temp)
            add_real_bitrate(temp, kbps)
            action = "tagged"
        else:
            action = None
            if mode == "auto" and kbps == analysis.real_kbps and recoverability(source) >= CLEAN_FIT:
                try:
                    reconstruct(source, temp, kbps)
                    action = "reconstructed"
                except Exception:
                    temp.unlink(missing_ok=True)
            if action is None:
                reencode(source, temp, kbps, ffmpeg)
                action = "re-encoded"
            copy_tags(source, temp, kbps)
        os.replace(temp, target)
    except Exception as e:
        temp.unlink(missing_ok=True)
        return ConvertResult(rel, "failed", f"{type(e).__name__}: {e}")

    return ConvertResult(rel, action, f"{analysis.claimed_kbps} -> {kbps} kbps")


def _ignore_ctrl_c() -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def convert_folder(
    root: Path,
    output: Path,
    ffmpeg: str,
    mode: str = "auto",
    overrides: dict[str, int] | None = None,
    step_up: bool = False,
    workers: int | None = None,
    on_progress: Callable[[int, int, ConvertResult], None] | None = None,
) -> list[ConvertResult]:
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError("The output folder can not be inside the input folder")
    overrides = overrides or {}
    files = find_mp3_files(root)
    results = []

    pool = ProcessPoolExecutor(max_workers=workers, initializer=_ignore_ctrl_c)
    try:
        futures = []
        for source in files:
            rel = source.relative_to(root)
            futures.append(pool.submit(_convert_one, source, output / rel, rel, ffmpeg, mode,
                                       overrides.get(_key(rel)), step_up))
        for done, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            if on_progress:
                on_progress(done, len(files), result)
    except KeyboardInterrupt:
        pool.shutdown(wait=False, cancel_futures=True)
        raise

    pool.shutdown()
    return results


def write_convert_report(results: list[ConvertResult], root: Path, output: Path,
                         path: Path) -> None:
    by_action: dict[str, list[ConvertResult]] = {}
    for r in results:
        by_action.setdefault(r.action, []).append(r)

    lines = [
        "Bitrater-90000 convert report",
        f"Input:   {root}",
        f"Output:  {output}",
        f"Created: {datetime.now():%Y-%m-%d %H:%M}",
        "Tracks:  " + ", ".join(f"{len(v)} {k}" for k, v in sorted(by_action.items())),
    ]
    for action in ("reconstructed", "re-encoded", "tagged", "failed", "copied"):
        group = sorted(by_action.get(action, []), key=lambda r: str(r.path).lower())
        if not group:
            continue
        lines += ["", action.upper(), ""]
        for r in group:
            lines.append(f"  {r.detail:24}  {r.path}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")