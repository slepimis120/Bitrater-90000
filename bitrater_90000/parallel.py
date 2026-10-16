import signal
import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Callable


def _ignore_ctrl_c() -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def run_parallel(
    func: Callable,
    tasks: list[tuple],
    workers: int | None = None,
    on_result: Callable[[int, int, object], None] | None = None,
    cancel: threading.Event | None = None,
) -> list:
    results = []
    stopped = False
    pool = ProcessPoolExecutor(max_workers=workers, initializer=_ignore_ctrl_c)
    try:
        futures = [pool.submit(func, *task) for task in tasks]
        for done, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            if on_result:
                on_result(done, len(tasks), result)
            if cancel is not None and cancel.is_set():
                stopped = True
                break
    except KeyboardInterrupt:
        stopped = True
        raise
    finally:
        pool.shutdown(wait=not stopped, cancel_futures=stopped)
    return results