from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

from bitrater_90000.report import TrackResult, format_cutoff

COLUMNS = ["Status", "Real kbps", "Claimed kbps", "Cutoff", "File"]
STATUS, REAL, CLAIMED, CUTOFF, FILE = range(len(COLUMNS))

SORT_ROLE = Qt.UserRole + 1
RESULT_ROLE = Qt.UserRole + 2

STATUS_RANK = {"DAMAGED": 0, "ERROR": 1, "FAKE": 2, "UNSURE": 3, "OK": 4}

STATUS_COLORS = {
    "FAKE": QColor(230, 70, 70, 70),
    "UNSURE": QColor(230, 180, 40, 70),
    "DAMAGED": QColor(140, 140, 140, 90),
    "ERROR": QColor(140, 140, 140, 90),
}


class ResultsModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.root: Path | None = None
        self.results: list[TrackResult] = []

    def reset(self, root: Path, results: list[TrackResult] | None = None) -> None:
        self.beginResetModel()
        self.root = root
        self.results = list(results or [])
        self.endResetModel()

    def add(self, result: TrackResult) -> None:
        row = len(self.results)
        self.beginInsertRows(QModelIndex(), row, row)
        self.results.append(result)
        self.endInsertRows()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.results)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r = self.results[index.row()]
        a = r.analysis
        column = index.column()

        if role == Qt.DisplayRole:
            if column == STATUS:
                return r.status
            if column == FILE:
                return str(self.relative(r))
            if a is None:
                return "-"
            if column == REAL:
                return f"~{a.best_guess_kbps}?" if a.real_kbps is None else str(a.real_kbps)
            if column == CLAIMED:
                return str(a.claimed_kbps)
            if column == CUTOFF:
                return format_cutoff(a)

        elif role == SORT_ROLE:
            if column == STATUS:
                return STATUS_RANK[r.status]
            if column == FILE:
                return str(self.relative(r)).lower()
            if a is None:
                return -1.0
            if column == REAL:
                real = a.real_kbps if a.real_kbps is not None else 10_000
                return real + a.cutoff_hz / 1e6
            if column == CLAIMED:
                return float(a.claimed_kbps)
            if column == CUTOFF:
                return a.cutoff_hz

        elif role == Qt.BackgroundRole:
            return STATUS_COLORS.get(r.status)

        elif role == Qt.TextAlignmentRole:
            if column in (REAL, CLAIMED, CUTOFF):
                return int(Qt.AlignRight | Qt.AlignVCenter)

        elif role == Qt.ToolTipRole:
            if column == REAL and a is not None and a.real_kbps is None:
                return "Uncertain. Best guess from the highest frequency with content."
            return r.error or str(r.path)

        elif role == RESULT_ROLE:
            return r

        return None

    def relative(self, r: TrackResult) -> Path:
        try:
            return r.path.relative_to(self.root)
        except ValueError:
            return r.path


class ResultsFilter(QSortFilterProxyModel):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._statuses: set[str] | None = None    # None = all
        self._search = ""
        self.setSortRole(SORT_ROLE)

    def set_statuses(self, statuses: set[str] | None) -> None:
        self._statuses = statuses
        self.invalidateFilter()

    def set_search(self, text: str) -> None:
        self._search = text.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        r = self.sourceModel().results[row]
        if self._statuses is not None and r.status not in self._statuses:
            return False
        if self._search and self._search not in str(r.path).lower():
            return False
        return True