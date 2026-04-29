import json
import logging
import logging.handlers
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

task_id_var: ContextVar[str] = ContextVar("task_id", default="")

# Dynamically determine built-in LogRecord attributes so extras are cleanly separated.
_sample = logging.LogRecord("", 0, "", 0, "", (), None)
_BUILTIN_ATTRS = frozenset(_sample.__dict__.keys()) | {"message", "asctime"}
del _sample


class JsonLinesFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        extras = {k: v for k, v in record.__dict__.items() if k not in _BUILTIN_ATTRS}
        entry = {
            **extras,  # extras first
            "ts": (
                datetime.fromtimestamp(record.created, tz=timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%S.")
                + f"{int(record.msecs):03d}Z"
            ),
            "level": record.levelname,
            "logger": record.name,
            "task_id": task_id_var.get(),
            "msg": record.message,
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class HumanFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        task_id = task_id_var.get()
        task_part = f" [task:{task_id}]" if task_id else ""
        base = (
            f"{self.formatTime(record, '%Y-%m-%d %H:%M:%S')} "
            f"{record.levelname:<5} [{record.name}]{task_part} {record.getMessage()}"
        )
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        if record.stack_info:
            base += "\n" + self.formatStack(record.stack_info)
        return base


def setup_logging(
    log_file: str = "app.log",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    level: int = logging.INFO,
) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(JsonLinesFormatter())
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(HumanFormatter())
    root.addHandler(stream_handler)
