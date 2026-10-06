from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import signal
from typing import Callable

from bitrater_90000.analyzer import AnalysisResult, DamagedFileError, analyze_file

FAKE_MARGIN_KBPS = 32


@dataclass
class TrackResult:
    path: Path
    analysis: AnalysisResult | None = None
    error: str | None = None
    damaged: bool = False

    @property
    def status(self) -> str:
        if self.damaged:
            return "DAMAGED"
        if self.error:
            return "ERROR"
        if self.analysis.real_kbps is None:
            return "UNSURE"
        if self.analysis.claimed_kbps - self.analysis.real_kbps >= FAKE_MARGIN_KBPS:
            return "FAKE"
        return "OK"

def _ignore_ctrl_c() -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)

def find_mp3_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".mp3")


def _analyze_one(path: Path, ffmpeg: str) -> TrackResult:
    try:
        return TrackResult(path, analysis=analyze_file(path, ffmpeg))
    except DamagedFileError as e:
        return TrackResult(path, error=str(e), damaged=True)
    except Exception as e:
        return TrackResult(path, error=f"{type(e).__name__}: {e}")


def analyze_folder(
    root: Path,
    ffmpeg: str,
    workers: int | None = None,
    on_progress: Callable[[int, int, TrackResult], None] | None = None,
) -> list[TrackResult]:
    files = find_mp3_files(root)
    results = []

    pool = ProcessPoolExecutor(max_workers=workers, initializer=_ignore_ctrl_c)
    try:
        futures = [pool.submit(_analyze_one, f, ffmpeg) for f in files]
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


def _by_path(result: TrackResult) -> str:
    return str(result.path).lower()


def _worst_first(result: TrackResult):
    a = result.analysis
    return a.real_kbps, a.cutoff_hz, _by_path(result)

def _format_cutoff(a: AnalysisResult) -> str:
    prefix = "" if a.sharp_cutoff else "~"
    return f"{prefix}{a.cutoff_hz / 1000:.1f} kHz"

def write_report(results: list[TrackResult], root: Path, out_path: Path) -> None:
    rated = sorted((r for r in results if r.status in ("OK", "FAKE")), key=_worst_first)
    unsure = sorted((r for r in results if r.status == "UNSURE"), key=_by_path)
    errors = sorted((r for r in results if r.status == "ERROR"), key=_by_path)
    damaged = sorted((r for r in results if r.status == "DAMAGED"), key=_by_path)
    fake_count = sum(r.status == "FAKE" for r in rated)

    lines = [
        "Bitrater-90000 report",
        f"Folder:  {root}",
        f"Created: {datetime.now():%Y-%m-%d %H:%M}",
        f"Tracks:  {len(results)} total, {len(rated) - fake_count} OK, {fake_count} fake, "
        f"{len(unsure)} uncertain, {len(damaged)} damaged, {len(errors)} errors",
        "Cutoff:  sharp codec cutoff, or ~ = no cutoff, content naturally reaches this frequency",
        "",
        f"{'REAL':>5}  {'CLAIMED':>7}  {'CUTOFF':>10}  {'STATUS':<6}  FILE",
    ]

    for r in rated:
        a = r.analysis
        lines.append(
            f"{a.real_kbps:>5}  {a.claimed_kbps:>7}  {_format_cutoff(a):>10}  "
            f"{r.status:<6}  {r.path.relative_to(root)}"
        )

    if unsure:
        lines += ["", "UNCERTAIN (no clear cutoff, content fades out below 19.5 kHz - check in Spek)", ""]
        for r in unsure:
            a = r.analysis
            lines.append(
                f"{a.claimed_kbps:>7} kbps claimed, content up to {a.cutoff_hz / 1000:.1f} kHz  "
                f"{r.path.relative_to(root)}"
            )

    if damaged:
        lines += ["", "DAMAGED (audio data is corrupted, re-download these)", ""]
        for r in damaged:
            lines.append(f"{r.path.relative_to(root)}\n    {r.error}")

    if errors:
        lines += ["", "ERRORS", ""]
        for r in errors:
            lines.append(f"{r.path.relative_to(root)}\n    {r.error}")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")