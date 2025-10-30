import logging
import sys
import threading


class _BoardState:
    def __init__(self, stream):
        self.stream = stream
        self.lock = threading.Lock()
        self.enabled = bool(getattr(stream, "isatty", lambda: False)())
        self.current = ""
        self._lines = []
        self._line_count = 0

    def _clear_previous(self) -> None:
        if not self._line_count:
            return
        # move cursor to first line of board
        self.stream.write("\r")
        for _ in range(self._line_count - 1):
            self.stream.write("\x1b[1A")
        # clear each line
        for idx in range(self._line_count):
            self.stream.write("\r\x1b[2K")
            if idx < self._line_count - 1:
                self.stream.write("\n")
        # return to top ready for redraw
        if self._line_count > 1:
            self.stream.write("\r")
            for _ in range(self._line_count - 1):
                self.stream.write("\x1b[1A")
        self._line_count = 0

    def _render(self, lines):
        for idx, line in enumerate(lines):
            self.stream.write("\r\x1b[2K" + line)
            if idx < len(lines) - 1:
                self.stream.write("\n")
        self.stream.flush()
        self._line_count = len(lines)

    def update(self, text: str) -> None:
        if not self.enabled:
            return
        lines = text.splitlines() or [text]
        with self.lock:
            self._clear_previous()
            self._render(lines)
            self.current = text
            self._lines = lines

    def suspend(self) -> bool:
        if not self.enabled or not self._lines:
            return False
        with self.lock:
            self._clear_previous()
        return True

    def resume(self) -> None:
        if not self.enabled or not self._lines:
            return
        with self.lock:
            self._render(self._lines)

    def clear(self) -> None:
        if not self.enabled or not self._lines:
            return
        with self.lock:
            self._clear_previous()
            self.stream.write("\r\x1b[2K\n")
            self.stream.flush()
            self.current = ""
            self._lines = []
            self._line_count = 0


board_state = _BoardState(sys.stderr)


class BoardAwareHandler(logging.StreamHandler):
    def __init__(self, stream=None):
        super().__init__(stream or sys.stderr)

    def emit(self, record):
        if board_state.suspend():
            try:
                super().emit(record)
            finally:
                board_state.resume()
        else:
            super().emit(record)


def configure_logging(level, fmt, datefmt):
    handler = BoardAwareHandler()
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    logging.basicConfig(level=level, handlers=[handler], force=True)
    return board_state
