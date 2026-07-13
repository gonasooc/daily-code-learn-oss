"""스레드 안전한 터미널 진행 표시."""

import sys
import threading

from lib.colors import dim, cyan, safe_terminal_text


class ProgressDisplay:
    """병렬 작업의 진행 상황을 단일 라인으로 표시한다."""

    def __init__(self, total):
        self._total = total
        self._done = 0
        self._lock = threading.Lock()
        self._is_tty = sys.stderr.isatty()

    def update(self, project_name, status):
        """현재 작업 상태를 표시한다."""
        if not self._is_tty:
            return
        with self._lock:
            label = f"[{self._done}/{self._total}]"
            safe_status = safe_terminal_text(status)
            safe_project_name = safe_terminal_text(project_name)
            line = (
                f"{dim(label, stream=sys.stderr)} {safe_status}: "
                f"{cyan(safe_project_name, stream=sys.stderr)}"
            )
            sys.stderr.write(f"\r\033[K{line}")
            sys.stderr.flush()

    def complete_one(self):
        """완료 카운터를 1 증가시킨다."""
        with self._lock:
            self._done += 1

    def finish(self):
        """진행 표시 줄을 지운다."""
        if not self._is_tty:
            return
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()
