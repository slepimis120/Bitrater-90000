from collections import Counter
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from bitrater_90000.convert import ConvertResult, convert_folder, write_convert_report
from bitrater_90000.ffmpeg_tools import find_ffmpeg
from bitrater_90000.gui.widgets import FolderPicker
from bitrater_90000.gui.worker import start_worker
from bitrater_90000.report import TrackResult

MODE_LABELS = {
    "auto": "Auto: reconstruct the original when possible, otherwise re-encode",
    "reencode": "Re-encode: always re-encode to the real bitrate",
    "tag": "Tag only: write the real bitrate into a tag, keep the audio",
}
ACTION_ORDER = ["reconstructed", "re-encoded", "tagged", "copied", "failed"]
REPORT_NAME = "bitrater_convert_report.txt"


class ConvertTab(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._analysis_root: Path | None = None
        self._analysis: list[TrackResult] = []
        self._results: list[ConvertResult] = []
        self._thread = None
        self._worker = None

        self.input = FolderPicker("Music folder:")
        self.output = FolderPicker("Output folder:")

        self.mode = QComboBox()
        for mode, label in MODE_LABELS.items():
            self.mode.addItem(label, mode)

        self.step_up = QCheckBox("Re-encode one bitrate step higher (less quality loss, bigger files)")
        self.guess_uncertain = QCheckBox(
            "Also convert uncertain tracks, using the best guess of their bitrate")

        options = QFormLayout()
        options.addRow("Mode:", self.mode)
        options.addRow("", self.step_up)
        options.addRow("", self.guess_uncertain)

        self.start_button = QPushButton("Convert")
        self.start_button.clicked.connect(self.start)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        self.open_button = QPushButton("Open output folder")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_output)

        self.progress = QProgressBar()
        self.progress.setFormat("%v / %m")
        self.progress.setTextVisible(False)

        buttons = QHBoxLayout()
        buttons.addWidget(self.progress, stretch=1)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.open_button)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 9))
        self.log.setPlaceholderText("What happens with every track will be shown here.")

        self.summary = QLabel("Original files are never changed, everything is written "
                              "into the output folder.")

        layout = QVBoxLayout(self)
        layout.addWidget(self.input)
        layout.addWidget(self.output)
        layout.addLayout(options)
        layout.addLayout(buttons)
        layout.addWidget(self.log, stretch=1)
        layout.addWidget(self.summary)

    @property
    def selected_mode(self) -> str:
        return self.mode.currentData()

    def set_analysis(self, root: Path, results: list[TrackResult]) -> None:
        self._analysis_root = root
        self._analysis = list(results)

    def start(self) -> None:
        root, output = self.input.path, self.output.path
        if root is None or not root.is_dir():
            QMessageBox.warning(self, "Bitrater-90000", "Choose an existing music folder first.")
            return
        if output is None:
            QMessageBox.warning(self, "Bitrater-90000", "Choose an output folder first.")
            return
        root, output = root.resolve(), output.resolve()
        if output.is_relative_to(root):
            QMessageBox.warning(self, "Bitrater-90000",
                                "The output folder can not be inside the music folder.")
            return
        if output.is_dir() and any(output.iterdir()):
            answer = QMessageBox.question(
                self, "Bitrater-90000",
                "The output folder is not empty. Tracks with the same name will be replaced.\n\n"
                "Continue?")
            if answer != QMessageBox.Yes:
                return

        analyzed = self._analysis if self._analysis_root == root else None
        ffmpeg = find_ffmpeg()
        mode, step_up = self.selected_mode, self.step_up.isChecked()
        guess = self.guess_uncertain.isChecked()

        def job(on_progress, cancel):
            return convert_folder(root, output, ffmpeg, mode, {}, step_up, None, on_progress,
                                  cancel, analyzed, guess)

        self._root, self._output = root, output
        self._results = []
        self._thread, self._worker = start_worker(job)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.finished.connect(self._on_thread_finished)

        self.log.clear()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(True)
        self.summary.setText("Analyzing and converting..." if analyzed is None else "Converting...")
        self._set_running(True)
        self._thread.start()

    def stop(self) -> None:
        if self._worker:
            self._worker.cancel.set()
            self.stop_button.setEnabled(False)
            self.summary.setText("Stopping after the tracks that are being converted...")

    def wait(self) -> None:
        if self._thread:
            self.stop()
            self._thread.wait()

    def _on_progress(self, done: int, total: int, result: ConvertResult) -> None:
        self._results.append(result)
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.log.appendPlainText(f"{result.action:<14} {result.detail:<26} {result.path}")
        self.summary.setText(self._summary_text())

    def _on_finished(self, results: list) -> None:
        report = self._output / REPORT_NAME
        write_convert_report(results, self._root, self._output, report)
        stopped = self._worker.cancel.is_set()
        text = f"{self._summary_text()}. Report: {report}"
        self.summary.setText(f"Stopped. {text}" if stopped else f"Done. {text}")

    def _on_failed(self, message: str) -> None:
        self.summary.setText("Conversion failed.")
        QMessageBox.critical(self, "Bitrater-90000", f"Conversion failed:\n{message}")

    def _on_thread_finished(self) -> None:
        self._thread.deleteLater()
        self._worker.deleteLater()
        self._thread = self._worker = None
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.open_button.setEnabled(not running and bool(self._results))
        for widget in (self.input, self.output, self.mode, self.step_up, self.guess_uncertain):
            widget.setEnabled(not running)

    def _summary_text(self) -> str:
        counts = Counter(r.action for r in self._results)
        parts = [f"{counts[a]} {a}" for a in ACTION_ORDER if counts[a]]
        return f"{len(self._results)} tracks: " + ", ".join(parts)

    def _open_output(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output)))