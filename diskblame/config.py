import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .format import parse_size

DEFAULT_EXCLUDE = [
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".DS_Store",
    "lost+found",
]

DEFAULT_MIN_FILE_SIZE = 1024**2


@dataclass
class Config:
    db_path: Path
    exclude: list = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    min_file_size: int = DEFAULT_MIN_FILE_SIZE
    follow_symlinks: bool = False


def _home():
    return Path.home()


def config_path():
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "diskblame" / "config.toml"
    return _home() / ".config" / "diskblame" / "config.toml"


def data_path():
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / "diskblame" / "diskblame.db"
    return _home() / ".local" / "share" / "diskblame" / "diskblame.db"


def expand_path(value):
    return Path(os.path.expandvars(os.path.expanduser(str(value))))


def load_config(path=None):
    path = expand_path(path) if path else config_path()
    db_path = data_path()
    exclude = list(DEFAULT_EXCLUDE)
    min_file_size = DEFAULT_MIN_FILE_SIZE
    follow_symlinks = False

    if path.exists():
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        scan = data.get("scan", {})
        if isinstance(scan.get("exclude"), list):
            exclude = [str(item) for item in scan["exclude"]]
        if "min_file_size" in scan:
            value = scan["min_file_size"]
            min_file_size = value if isinstance(value, int) else parse_size(str(value))
        if "follow_symlinks" in scan:
            follow_symlinks = bool(scan["follow_symlinks"])
        db_section = data.get("db", {})
        if "path" in db_section:
            db_path = expand_path(db_section["path"])

    return Config(
        db_path=db_path,
        exclude=exclude,
        min_file_size=min_file_size,
        follow_symlinks=follow_symlinks,
    )


def config_text():
    return """[scan]
exclude = [".git", ".hg", ".svn", "__pycache__", ".DS_Store", "lost+found"]
min_file_size = "1MiB"
follow_symlinks = false

[db]
path = "~/.local/share/diskblame/diskblame.db"
"""


def write_default_config(path=None):
    path = expand_path(path) if path else config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(config_text(), encoding="utf-8")
    return path
