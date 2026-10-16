import os
import subprocess
from collections import Counter
from pathlib import Path

from PySide6.QtCore import QModelIndex, QPoint, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox,
    QProgressBar, QPushButton, QTableView, QVBoxLayout, QWidget,
)

from bitrater_90000.ffmpeg_tools import find_ffmpeg
from bitrater_90000.gui.results_model import FILE, REAL, RESULT_ROLE, ResultsFilter, ResultsModel
from bitrater_90000.gui.widgets import FolderPicker
from bitrater_90000.gui.worker import start_worker
from bitrater_90000.report import TrackResult, analyze_folder, write_report

STATUS_ORDER = ["OK", "FAKE", "UNSURE", "DAMAGED", "ERROR"]

FILTERS = {
    "All tracks": None,
    "Fake": {"FAKE"},
    "Uncertain": {"UNSURE"},
    "Damaged and errors": {"DAMAGED", "ERROR"},
    "Everything but OK": {"FAKE", "UNSURE", "DAMAGED", "ERROR"},
    "OK": {"OK"},
}


class AnalyzeTab(QWidget):
    analysis_done = Signal(object, list)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.root: Path | None = None
        self._thread = None
        self._worker = None

        self.folder = FolderPicker("Music folder:")

        self.start_button = QPushButton("Analyze")
        self.start_button.clicked.connect(self.start)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)

        self.progress = QProgressBar()
        self.progress.setFormat("%v / %m")
        self.progress.setTextVisible(False)

        self.model = ResultsModel(self)
        self.filter = ResultsFilter(self)
        self.filter.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.filter)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(REAL, Qt.AscendingOrder)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setEditTriggers(QTableView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(22)
        header = self.table.horizontalHeader()
        for column in range(FILE):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(FILE, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self._open_location)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)

        self.show_filter = QComboBox()
        self.show_filter.addItems(FILTERS)
        self.show_filter.currentTextChanged.connect(
            lambda name: self.filter.set_statuses(FILTERS[name]))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by artist, title or folder...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter.set_search)

        self.summary = QLabel("Choose a folder and press Analyze.")
        self.save_button = QPushButton("Save report...")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save_report)

        buttons = QHBoxLayout()
        buttons.addWidget(self.progress, stretch=1)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Show:"))
        filters.addWidget(self.show_filter)
        filters.addSpacing(12)
        filters.addWidget(self.search, stretch=1)

        bottom = QHBoxLayout()
        bottom.addWidget(self.summary, stretch=1)
        bottom.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.folder)
        layout.addLayout(buttons)
        layout.addLayout(filters)
        layout.addWidget(self.table, stretch=1)
        layout.addLayout(bottom)

    @property
    def results(self) -> list[TrackResult]:
        return self.model.results

    @property
    def running(self) -> bool:
        return self._thread is not None

    def start(self) -> None:
        root = self.folder.path
        if root is None or not root.is_dir():
            QMessageBox.warning(self, "Bitrater-90000", "Choose an existing music folder first.")
            return

        self.root = root.resolve()
        self.model.reset(self.root)
        ffmpeg = find_ffmpeg()

        def job(on_progress, cancel):
            return analyze_folder(self.root, ffmpeg, None, on_progress, cancel)

        self._thread, self._worker = start_worker(job)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.finished.connect(self._on_thread_finished)

        self.progress.setRange(0, 0)
        self.progress.setTextVisible(True)
        self.summary.setText("Looking for MP3 files...")
        self._set_running(True)
        self._thread.start()

    def stop(self) -> None:
        if self._worker:
            self._worker.cancel.set()
            self.stop_button.setEnabled(False)
            self.summary.setText("Stopping after the tracks that are being analyzed...")

    def wait(self) -> None:
        if self._thread:
            self.stop()
            self._thread.wait()

    def _on_progress(self, done: int, total: int, result: TrackResult) -> None:
        self.model.add(result)
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.summary.setText(self._summary_text())

    def _on_finished(self, results: list) -> None:
        stopped = self._worker.cancel.is_set()
        text = self._summary_text()
        self.summary.setText(f"Stopped. {text}" if stopped else text)
        self.analysis_done.emit(self.root, self.results)

    def _on_failed(self, message: str) -> None:
        self.summary.setText("Analysis failed.")
        QMessageBox.critical(self, "Bitrater-90000", f"Analysis failed:\n{message}")

    def _on_thread_finished(self) -> None:
        self._thread.deleteLater()
        self._worker.deleteLater()
        self._thread = self._worker = None
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.folder.setEnabled(not running)
        self.save_button.setEnabled(not running and bool(self.results))

    def _summary_text(self) -> str:
        counts = Counter(r.status for r in self.results)
        parts = [f"{counts[s]} {s.lower()}" for s in STATUS_ORDER if counts[s]]
        return f"{len(self.results)} tracks: " + ", ".join(parts) if parts else "No MP3 files found."

    def _result_at(self, index: QModelIndex) -> TrackResult | None:
        return index.data(RESULT_ROLE) if index.isValid() else None

    def _context_menu(self, pos: QPoint) -> None:
        result = self._result_at(self.table.indexAt(pos))
        if result is None:
            return
        menu = QMenu(self)
        menu.addAction("Open file location", lambda: self._open_location(self.table.indexAt(pos)))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _open_location(self, index: QModelIndex) -> None:
        result = self._result_at(index)
        if result is None:
            return
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", str(result.path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(result.path.parent)))

    def _save_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save report", "bitrater_report.txt",
                                              "Text files (*.txt)")
        if path:
            write_report(self.results, self.root, Path(path))
            self.summary.setText(f"Report saved to {path}")