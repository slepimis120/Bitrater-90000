import multiprocessing
import os
import sys

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")


def main() -> None:
    from PySide6.QtWidgets import QApplication
    from bitrater_90000.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Bitrater-90000")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()