import threading
import time
from pathlib import Path

from core.filelock import file_lock


def test_file_lock_serializes_two_threads(tmp_path):
    lock_path = tmp_path / "test.lock"
    order = []

    def worker(label, hold_seconds):
        with file_lock(lock_path):
            order.append(f"{label}-start")
            time.sleep(hold_seconds)
            order.append(f"{label}-end")

    t1 = threading.Thread(target=worker, args=("a", 0.2))
    t2 = threading.Thread(target=worker, args=("b", 0.0))
    t1.start()
    time.sleep(0.05)  # ensure t1 acquires first
    t2.start()
    t1.join()
    t2.join()

    # t1 must fully finish (start AND end) before t2 starts, proving mutual exclusion —
    # if the lock didn't work, t2's start would interleave between t1's start and end.
    assert order == ["a-start", "a-end", "b-start", "b-end"]


def test_file_lock_reentrant_across_separate_calls(tmp_path):
    lock_path = tmp_path / "test.lock"
    with file_lock(lock_path):
        pass
    with file_lock(lock_path):
        pass
