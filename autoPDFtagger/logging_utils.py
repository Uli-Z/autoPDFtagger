import logging
import sys
import threading


class _BoardState:
    def __init__(self, stream):
        self.stream = stream
        self.lock = threading.Lock()
        self.enabled = bool(getattr(stream, "isatty", lambda: False)())
        self.current = ""

    def update(self, text: str) -> None:
        if not self.enabled:
            return
        with self.lock:
            self.stream.write("\r\x1b[2K")
            self.stream.write(text)
            self.stream.flush()
            self.current = text

    def clear(self) -> None:
        if not self.enabled:
            return
        with self.lock:
            self.stream.write("\r\x1b[2K\n")
            self.stream.flush()
            self.current = ""


board_state = _BoardState(sys.stderr)


class BoardAwareHandler(logging.StreamHandler):
    def __init__(self, stream=None):
        super().__init__(stream or sys.stderr)

    def emit(self, record):
        if board_state.enabled and board_state.current:
            with board_state.lock:
                board_state.stream.write("\r\x1b[2K")
                super().emit(record)
                if board_state.current:
                    board_state.stream.write(board_state.current)
                    board_state.stream.flush()
        else:
            super().emit(record)


def configure_logging(level, fmt, datefmt):
    handler = BoardAwareHandler()
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    logging.basicConfig(level=level, handlers=[handler], force=True)
    return board_state
