import fnmatch
import os
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ScanResult:
    root: str
    total_size: int
    total_files: int
    total_dirs: int
    skipped: int
    elapsed_ms: int
    dirs: list
    files: list


def should_exclude(name, relative, patterns):
    for pattern in patterns:
        if not pattern:
            continue
        if name == pattern:
            return True
        if fnmatch.fnmatch(name, pattern):
            return True
        if "/" in pattern and fnmatch.fnmatch(relative, pattern):
            return True
    return False


def _stat_size(stat):
    blocks = getattr(stat, "st_blocks", 0)
    if blocks:
        return max(0, blocks * 512)
    return max(0, stat.st_size)


def scan(root, exclude=None, min_file_size=1024**2, follow_symlinks=False):
    exclude = list(exclude or [])
    root_path = Path(root).expanduser().absolute()
    if not root_path.exists():
        raise FileNotFoundError(str(root_path))
    if not root_path.is_dir():
        raise ValueError(f"not a directory: {root_path}")

    started = time.monotonic()
    root_stat = root_path.stat()
    directories = {".": [0, 0, 0, root_stat.st_mtime]}
    files = []
    total_files = 0
    skipped = 0
    seen_inodes = set()
    visited_dirs = {os.path.realpath(root_path)}
    stack = [(".", str(root_path))]

    while stack:
        relative_dir, absolute_dir = stack.pop()
        try:
            entries = os.scandir(absolute_dir)
        except OSError:
            skipped += 1
            continue

        with entries:
            for entry in entries:
                name = entry.name
                relative = name if relative_dir == "." else f"{relative_dir}/{name}"
                if should_exclude(name, relative, exclude):
                    continue
                try:
                    if entry.is_symlink():
                        if not follow_symlinks:
                            continue
                        real = os.path.realpath(entry.path)
                        if real in visited_dirs:
                            continue
                        visited_dirs.add(real)

                    if entry.is_dir(follow_symlinks=follow_symlinks):
                        real = os.path.realpath(entry.path)
                        if real in visited_dirs:
                            continue
                        visited_dirs.add(real)
                        stat = entry.stat(follow_symlinks=follow_symlinks)
                        directories[relative] = [0, 0, 0, stat.st_mtime]
                        stack.append((relative, entry.path))
                        continue

                    if entry.is_file(follow_symlinks=follow_symlinks):
                        stat = entry.stat(follow_symlinks=follow_symlinks)
                        apparent = max(0, stat.st_size)
                        size = _stat_size(stat)
                        if getattr(stat, "st_nlink", 1) > 1:
                            key = (stat.st_dev, stat.st_ino)
                            if key in seen_inodes:
                                size = 0
                            else:
                                seen_inodes.add(key)
                        parent = directories[relative_dir]
                        parent[0] += size
                        parent[1] += 1
                        total_files += 1
                        if apparent >= min_file_size:
                            files.append(
                                (
                                    relative,
                                    size,
                                    apparent,
                                    stat.st_mtime,
                                    stat.st_ino,
                                    stat.st_mode,
                                )
                            )
                except OSError:
                    skipped += 1

    for relative in sorted(
        directories, key=lambda item: item.count("/"), reverse=True
    ):
        if relative == ".":
            continue
        parent_path = relative.rsplit("/", 1)[0] if "/" in relative else "."
        child = directories[relative]
        parent = directories[parent_path]
        parent[0] += child[0]
        parent[1] += child[1]
        parent[2] += child[2] + 1

    dir_rows = [
        (path, row[0], row[1], row[2] + 1, row[3])
        for path, row in directories.items()
    ]
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return ScanResult(
        root=str(root_path),
        total_size=directories["."][0],
        total_files=total_files,
        total_dirs=directories["."][2] + 1,
        skipped=skipped,
        elapsed_ms=elapsed_ms,
        dirs=dir_rows,
        files=files,
    )
