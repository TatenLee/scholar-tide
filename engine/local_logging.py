"""Private rotating diagnostics, including redaction of formatted tracebacks."""
import logging
import os
from logging.handlers import RotatingFileHandler

from engine.local_llm import load_config, redact


def configure_logging(root):
    path = root / ".local/logs/service.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    os.fchmod(fd, 0o600)
    os.close(fd)

    class PrivateFormatter(logging.Formatter):
        def format(self, record):
            try:
                config = load_config(root / "config/llm.local.yaml")
            except (ValueError, TypeError, OSError):
                return f"{record.levelname}: 配置不可读，已隐藏日志详情"
            return redact(super().format(record), config)

    class PrivateFileHandler(RotatingFileHandler):
        def _open(self):
            stream = super()._open()
            os.fchmod(stream.fileno(), 0o600)
            return stream

    formatter = PrivateFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    for handler in logger.handlers:
        handler.setFormatter(formatter)
        if isinstance(handler, RotatingFileHandler) and handler.baseFilename == str(path.resolve()):
            return path
    handler = PrivateFileHandler(path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return path
