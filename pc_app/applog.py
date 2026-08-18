"""Central in-app logger — thread-safe ring buffer, singleton."""
import time
import threading
from collections import deque

_MAX_LINES = 20000


class _AppLogger:
    def __init__(self):
        self._lines: deque[str] = deque(maxlen=_MAX_LINES)
        self._lock = threading.Lock()
        self._unread = 0

    def log(self, tag: str, msg: str):
        ts = time.strftime('%H:%M:%S')
        line = f'[{ts}] {tag:<5} {msg}'
        with self._lock:
            self._lines.append(line)
            self._unread += 1

    def get_lines(self) -> list:
        with self._lock:
            return list(self._lines)

    def consume_unread(self) -> int:
        with self._lock:
            n = self._unread
            self._unread = 0
            return n

    def clear(self):
        with self._lock:
            self._lines.clear()
            self._unread = 0

    def save(self, path: str):
        with self._lock:
            lines = list(self._lines)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')


app_log = _AppLogger()


def log(tag: str, msg: str):
    app_log.log(tag, msg)
