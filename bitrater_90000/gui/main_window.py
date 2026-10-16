from PySide6.QtWidgets import QMainWindow, QTabWidget
from PySide6.QtGui import QCloseEvent

from bitrater_90000.gui.analyze_tab import AnalyzeTab
from bitrater_90000.gui.convert_tab import ConvertTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bitrater-90000")
        self.resize(1100, 700)

        self.analyze_tab = AnalyzeTab()
        self.convert_tab = ConvertTab()

        tabs = QTabWidget()
        tabs.addTab(self.analyze_tab, "Analyze")
        tabs.addTab(self.convert_tab, "Convert")
        self.setCentralWidget(tabs)

        self.analyze_tab.folder.changed.connect(self.convert_tab.input.set_path)

        self.analyze_tab.analysis_done.connect(self.convert_tab.set_analysis)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.analyze_tab.wait()
        self.convert_tab.wait()
        event.accept()