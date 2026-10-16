from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget


class FolderPicker(QWidget):

    changed = Signal(str)

    def __init__(self, label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._edit = QLineEdit()
        self._edit.setPlaceholderText("Choose a folder...")
        self._edit.textChanged.connect(self.changed)

        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel(label)
        title.setMinimumWidth(90)
        layout.addWidget(title)
        layout.addWidget(self._edit, stretch=1)
        layout.addWidget(browse)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder", self._edit.text())
        if folder:
            self._edit.setText(str(Path(folder)))

    @property
    def path(self) -> Path | None:
        text = self._edit.text().strip()
        return Path(text) if text else None

    def set_path(self, path: Path | str) -> None:
        self._edit.setText(str(path))