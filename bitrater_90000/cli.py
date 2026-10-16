import argparse
import multiprocessing
from pathlib import Path
import sys
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from bitrater_90000.ffmpeg_tools import find_ffmpeg
from bitrater_90000.report import analyze_folder, write_report
from bitrater_90000.convert import MODES, convert_folder, load_overrides, write_convert_report


def cmd_report(args) -> None:
    root = args.folder.resolve()
    if not root.is_dir():
        raise SystemExit(f"Folder does not exist: {root}")

    ffmpeg = find_ffmpeg()

    def on_progress(done, total, result):
        print(f"[{done}/{total}] {result.status:<6} {result.path.relative_to(root)}")

    results = analyze_folder(root, ffmpeg, args.jobs, on_progress)
    write_report(results, root, args.output)
    print(f"\nReport saved to: {args.output.resolve()}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        prog="bitrater_90000",
        description="Detects the real bitrate of MP3 tracks.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    report = sub.add_parser("report", help="analyze all MP3 files in a folder and write a report")
    report.add_argument("folder", type=Path, help="folder with music (subfolders included)")
    report.add_argument("-o", "--output", type=Path, default=Path("bitrater_report.txt"),
                        help="report file (default: bitrater_report.txt)")
    report.add_argument("-j", "--jobs", type=int, default=None,
                        help="number of parallel processes (default: number of CPU cores)")
    report.set_defaults(func=cmd_report)

    convert = sub.add_parser("convert", help="convert fake tracks to their real bitrate")
    convert.add_argument("folder", type=Path, help="folder with music (subfolders included)")
    convert.add_argument("output", type=Path, help="where to write the converted library")
    convert.add_argument("--mode", choices=MODES, default="auto",
                         help="auto: reconstruct when possible, otherwise re-encode (default); "
                              "reencode: always re-encode; tag: only write the real bitrate into a tag")
    convert.add_argument("--step-up", action="store_true",
                         help="re-encode one standard bitrate above the real one (less loss)")
    convert.add_argument("--guess-uncertain", action="store_true",
                         help="also convert uncertain tracks, using the best guess of their bitrate")
    convert.add_argument("--overrides", type=Path, default=None,
                         help="file with manual bitrates: '<kbps> <relative path>' per line")
    convert.add_argument("-r", "--report", type=Path, default=Path("bitrater_convert_report.txt"),
                         help="report file (default: bitrater_convert_report.txt)")
    convert.add_argument("-j", "--jobs", type=int, default=None,
                         help="number of parallel processes (default: number of CPU cores)")
    convert.set_defaults(func=cmd_convert)

    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        raise SystemExit(130)

def cmd_convert(args) -> None:
    root = args.folder.resolve()
    output = args.output.resolve()
    if not root.is_dir():
        raise SystemExit(f"Folder does not exist: {root}")

    ffmpeg = find_ffmpeg()
    overrides = load_overrides(args.overrides)

    def on_progress(done, total, result):
        print(f"[{done}/{total}] {result.action:<13} {result.detail:24} {result.path}")

    try:
        results = convert_folder(root, output, ffmpeg, args.mode, overrides, args.step_up,
                                 args.jobs, on_progress, guess_uncertain=args.guess_uncertain)
    except ValueError as e:
        raise SystemExit(str(e))
    write_convert_report(results, root, output, args.report)
    print(f"\nReport saved to: {args.report.resolve()}")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()