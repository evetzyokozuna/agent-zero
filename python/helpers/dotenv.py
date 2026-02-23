import os
import re
from typing import Any

from .files import get_abs_path
from dotenv import load_dotenv as _load_dotenv

KEY_AUTH_LOGIN = "AUTH_LOGIN"
KEY_AUTH_PASSWORD = "AUTH_PASSWORD"
KEY_RFC_PASSWORD = "RFC_PASSWORD"
KEY_ROOT_PASSWORD = "ROOT_PASSWORD"
_last_loaded_mtime: float | None = None

def load_dotenv():
    global _last_loaded_mtime
    dotenv_path = get_dotenv_file_path()
    _load_dotenv(dotenv_path, override=True)
    try:
        _last_loaded_mtime = os.path.getmtime(dotenv_path)
    except OSError:
        _last_loaded_mtime = None


def get_dotenv_file_path():
    return get_abs_path("usr/.env")

def get_dotenv_value(key: str, default: Any = None):
    _refresh_dotenv_if_changed()
    return os.getenv(key, default)


def _refresh_dotenv_if_changed():
    global _last_loaded_mtime
    dotenv_path = get_dotenv_file_path()
    try:
        current_mtime = os.path.getmtime(dotenv_path)
    except OSError:
        return
    if _last_loaded_mtime is None or current_mtime > _last_loaded_mtime:
        load_dotenv()

def save_dotenv_value(key: str, value: str):
    if value is None:
        value = ""
    dotenv_path = get_dotenv_file_path()
    if not os.path.isfile(dotenv_path):
        with open(dotenv_path, "w") as f:
            f.write("")
    with open(dotenv_path, "r+") as f:
        lines = f.readlines()
        found = False
        for i, line in enumerate(lines):
            if re.match(rf"^\s*{key}\s*=", line):
                lines[i] = f"{key}={value}\n"
                found = True
        if not found:
            lines.append(f"\n{key}={value}\n")
        f.seek(0)
        f.writelines(lines)
        f.truncate()
    load_dotenv()
