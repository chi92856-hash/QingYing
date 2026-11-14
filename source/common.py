"""Lightweight values shared by the UI and media workers."""
import json
import os
import tempfile
from pathlib import Path

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff', '.avif'}

class Cancelled(Exception):
    pass


def load_settings(path):
    try:
        settings = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return settings if isinstance(settings, dict) else {}


def save_settings(path, settings):
    """Replace settings only after the complete new document is on disk."""
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(settings, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def saved_files_exist(value):
    try:
        files = json.loads(value)
        return (isinstance(files, list) and bool(files)
                and all(isinstance(p, str) and bool(p) and Path(p).is_file()
                        and Path(p).stat().st_size > 0 for p in files))
    except (OSError, ValueError, TypeError):
        return False


class LocalRPC:
    """Serialize with the caller's lock; drain a late reply before sending again."""
    def __init__(self, connection, timeout, timeout_message):
        self.connection = connection
        self.timeout = timeout
        self.timeout_message = timeout_message
        self.waiting = False

    def request(self, message):
        if self.waiting:
            if not self.connection.poll(0):
                raise TimeoutError('上一项操作仍在等待响应，请先完成文件选择或登录提示，稍后重试。')
            self.connection.recv()
            self.waiting = False
        self.connection.send(message)
        self.waiting = True
        if not self.connection.poll(self.timeout):
            raise TimeoutError(self.timeout_message)
        result = self.connection.recv()
        self.waiting = False
        return result
