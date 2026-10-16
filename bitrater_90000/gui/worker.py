import threading
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

Job = Callable[[Callable[[int, int, object], None], threading.Event], object]


class Worker(QObject):

    progress = Signal(int, int, object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, job: Job):
        super().__init__()
        self._job = job
        self.cancel = threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            result = self._job(self.progress.emit, self.cancel)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")
            return
        self.finished.emit(result)


def start_worker(job: Job) -> tuple[QThread, Worker]:
    thread = QThread()
    worker = Worker(job)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    return thread, worker