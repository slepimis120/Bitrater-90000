import argparse
import multiprocessing
from pathlib import Path
import sys
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from bitrater_90000.ffmpeg_tools import find_ffmpeg
from bitrater_90000.report import analyze_folder, write_report


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

    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        raise SystemExit(130)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()