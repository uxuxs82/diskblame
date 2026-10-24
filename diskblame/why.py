import hashlib
import os
import subprocess
from pathlib import Path

from . import db
from .format import human_age
from .scan import _stat_size

CACHE_NAMES = {
    ".cache",
    "cache",
    "caches",
    "tmp",
    "temp",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".gradle",
    ".npm",
    ".cargo",
    ".rustup",
    ".thumbnails",
    "thumbnails",
    "trash",
    ".trash",
}

DEPENDENCY_NAMES = {
    "node_modules",
    ".venv",
    "venv",
    "env",
    "vendor",
}

BUILD_NAMES = {
    "build",
    "dist",
    "target",
    ".next",
    ".nuxt",
    ".turbo",
    ".parcel-cache",
    "deriveddata",
}

TEXT_EXTENSIONS = {
    ".html",
    ".htm",
    ".css",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".md",
    ".txt",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".py",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".swift",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".xml",
    ".svg",
    ".sh",
}

MAGIC_TYPES = [
    (b"\xff\xd8\xff", "JPEG image"),
    (b"\x89PNG\r\n\x1a\n", "PNG image"),
    (b"GIF87a", "GIF image"),
    (b"GIF89a", "GIF image"),
    (b"BM", "BMP image"),
    (b"%PDF", "PDF document"),
    (b"PK\x03\x04", "ZIP archive"),
    (b"\x1f\x8b", "gzip archive"),
    (b"BZh", "bzip2 archive"),
    (b"\xfd7zXZ\x00", "xz archive"),
    (b"SQLite format 3\x00", "SQLite database"),
    (b"glTF", "glTF binary"),
    (b"\x7fELF", "ELF binary"),
    (b"MZ", "Windows executable"),
    (b"OggS", "Ogg media"),
    (b"fLaC", "FLAC audio"),
    (b"ID3", "MP3 audio"),
    (b"7z\xbc\xaf\x27\x1c", "7z archive"),
    (b"Rar!\x1a\x07", "RAR archive"),
    (b"\xfe\xed\xfa\xce", "Mach-O binary"),
    (b"\xfe\xed\xfa\xcf", "Mach-O binary"),
    (b"\xcf\xfa\xed\xfe", "Mach-O binary"),
]

EXTENSION_TYPES = {
    ".jpg": "JPEG image",
    ".jpeg": "JPEG image",
    ".png": "PNG image",
    ".gif": "GIF image",
    ".webp": "WebP image",
    ".bmp": "BMP image",
    ".heic": "HEIC image",
    ".heif": "HEIC image",
    ".avif": "AVIF image",
    ".pdf": "PDF document",
    ".zip": "ZIP archive",
    ".apk": "APK package",
    ".jar": "Java archive",
    ".glb": "glTF binary",
    ".mp4": "MP4 video",
    ".mkv": "Matroska video",
    ".webm": "WebM video",
    ".mov": "QuickTime video",
    ".avi": "AVI video",
    ".mp3": "MP3 audio",
    ".flac": "FLAC audio",
    ".ogg": "Ogg audio",
    ".wav": "WAV audio",
    ".sqlite": "SQLite database",
    ".db": "SQLite database",
    ".md": "Markdown document",
    ".txt": "text file",
    ".json": "JSON file",
    ".toml": "TOML file",
    ".yaml": "YAML file",
    ".yml": "YAML file",
    ".py": "Python source",
    ".js": "JavaScript source",
    ".ts": "TypeScript source",
    ".html": "HTML document",
    ".htm": "HTML document",
    ".css": "CSS stylesheet",
    ".sh": "shell script",
    ".exe": "Windows executable",
    ".dll": "Windows library",
    ".so": "shared library",
    ".iso": "disk image",
    ".img": "disk image",
    ".7z": "7z archive",
    ".rar": "RAR archive",
    ".tar": "tar archive",
    ".gz": "gzip archive",
    ".bz2": "bzip2 archive",
    ".xz": "xz archive",
}


def detect_type(path):
    try:
        with path.open("rb") as handle:
            head = handle.read(512)
    except OSError:
        return "unknown"
    for magic, label in MAGIC_TYPES:
        if head.startswith(magic):
            if label == "ZIP archive":
                suffix = path.suffix.lower()
                if suffix == ".apk":
                    return "APK package"
                if suffix == ".jar":
                    return "Java archive"
            return label
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WebP image"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "WAV audio"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"):
            return "HEIC image"
        if brand in (b"avif", b"avis"):
            return "AVIF image"
        return "MP4 video"
    if len(head) >= 262 and head[257:262] == b"ustar":
        return "tar archive"
    return EXTENSION_TYPES.get(path.suffix.lower(), path.suffix.lower().lstrip(".") or "file")


def image_dimensions(path, kind):
    try:
        if path.stat().st_size > 100 * 1024 * 1024:
            return None
        with path.open("rb") as handle:
            data = handle.read()
    except OSError:
        return None
    if kind == "PNG image" and len(data) >= 24:
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return [width, height]
    if kind == "GIF image" and len(data) >= 10:
        width = int.from_bytes(data[6:8], "little")
        height = int.from_bytes(data[8:10], "little")
        return [width, height]
    if kind == "JPEG image":
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                index += 2
                continue
            if index + 4 > len(data):
                break
            length = int.from_bytes(data[index + 2 : index + 4], "big")
            if marker in (
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            ):
                height = int.from_bytes(data[index + 5 : index + 7], "big")
                width = int.from_bytes(data[index + 7 : index + 9], "big")
                return [width, height]
            if length < 2:
                break
            index += 2 + length
    if kind == "WebP image" and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b"VP8X":
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
            return [width, height]
        if chunk == b"VP8 " and len(data) >= 30:
            width = int.from_bytes(data[26:28], "little") & 0x3FFF
            height = int.from_bytes(data[28:30], "little") & 0x3FFF
            return [width, height]
        if chunk == b"VP8L" and len(data) >= 25:
            bits = int.from_bytes(data[21:25], "little")
            width = (bits & 0x3FFF) + 1
            height = ((bits >> 14) & 0x3FFF) + 1
            return [width, height]
    if kind == "BMP image" and len(data) >= 26:
        width = int.from_bytes(data[18:22], "little", signed=True)
        height = int.from_bytes(data[22:26], "little", signed=True)
        return [width, abs(height)]
    return None


def find_git_root(path):
    start = path if path.is_dir() else path.parent
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _git(repo, args):
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def git_info(path):
    repo = find_git_root(path)
    if repo is None:
        return {}
    try:
        relative = str(path.relative_to(repo)).replace(os.sep, "/")
    except ValueError:
        return {}
    info = {"repo": str(repo), "tracked": False, "ignored": False}
    tracked = _git(repo, ["ls-files", "--error-unmatch", "--", relative])
    if tracked is not None and tracked.returncode == 0:
        info["tracked"] = True
    ignored = _git(repo, ["check-ignore", "-q", "--", relative])
    if ignored is not None and ignored.returncode == 0:
        info["ignored"] = True
    added = _git(
        repo,
        [
            "log",
            "-1",
            "--diff-filter=A",
            "--format=%h%x09%ad%x09%s",
            "--date=short",
            "--",
            relative,
        ],
    )
    if added is not None and added.returncode == 0 and added.stdout.strip():
        info["added"] = added.stdout.strip().replace("\t", " ")
    last = _git(
        repo,
        ["log", "-1", "--format=%h%x09%ad%x09%s", "--date=short", "--", relative],
    )
    if last is not None and last.returncode == 0 and last.stdout.strip():
        info["last"] = last.stdout.strip().replace("\t", " ")
    return info


def find_references(path, limit=20):
    name = path.name
    if not name:
        return []
    repo = find_git_root(path)
    if repo is not None:
        result = _git(repo, ["grep", "-n", "-I", "-F", "--", name])
        if result is not None and result.returncode == 0:
            matches = []
            for line in result.stdout.splitlines():
                parts = line.split(":", 2)
                if len(parts) >= 2:
                    matches.append([parts[0], int(parts[1]) if parts[1].isdigit() else 0])
                if len(matches) >= limit:
                    break
            return matches
        if result is not None and result.returncode == 1:
            return []

    root = repo or path.parent
    matches = []
    scanned = 0
    for current, dirs, files in os.walk(root):
        dirs[:] = [
            item
            for item in dirs
            if item not in {".git", "node_modules", ".venv", "venv", "__pycache__"}
        ]
        for filename in files:
            if scanned >= 2000 or len(matches) >= limit:
                break
            candidate = Path(current) / filename
            if candidate == path:
                continue
            if candidate.suffix.lower() not in TEXT_EXTENSIONS and candidate.suffix:
                continue
            try:
                if candidate.stat().st_size > 2 * 1024 * 1024:
                    continue
                text = candidate.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            scanned += 1
            for number, line in enumerate(text.splitlines(), 1):
                if name in line:
                    matches.append([str(candidate.relative_to(root)), number])
                    break
            if len(matches) >= limit:
                break
        if scanned >= 2000 or len(matches) >= limit:
            break
    return matches


def file_hash(path, size):
    digest = hashlib.sha256()
    chunk_size = 1024 * 1024
    with path.open("rb") as handle:
        if size <= 64 * 1024 * 1024:
            for chunk in iter(lambda: handle.read(chunk_size), b""):
                digest.update(chunk)
        else:
            digest.update(handle.read(chunk_size))
            handle.seek(-chunk_size, os.SEEK_END)
            digest.update(handle.read(chunk_size))
            digest.update(str(size).encode())
    return digest.hexdigest()


def find_duplicates(conn, snapshot, relative, size, limit=5):
    if conn is None or snapshot is None or size <= 0:
        return []
    rows = db.search_files_by_size(conn, snapshot["id"], size, relative)
    if not rows:
        return []
    root = Path(snapshot["root"])
    target = root / relative
    try:
        target_hash = file_hash(target, size)
    except OSError:
        return []
    duplicates = []
    for row in rows:
        candidate = root / row["path"]
        try:
            if candidate.stat().st_size != size:
                continue
            if file_hash(candidate, size) == target_hash:
                duplicates.append(row["path"])
        except OSError:
            continue
        if len(duplicates) >= limit:
            break
    return duplicates


def cache_reason(relative):
    parts = [part.lower() for part in relative.split("/")]
    for part in parts:
        if part in DEPENDENCY_NAMES:
            return "dependency directory"
        if part in BUILD_NAMES:
            return "build output"
        if part in CACHE_NAMES:
            return "cache or temporary directory"
    return None


def recommendation(info):
    if info.get("git", {}).get("tracked"):
        return "tracked by git, keep unless you remove it from the repo"
    if info.get("duplicates"):
        return "duplicate, one copy may be enough"
    if info.get("references"):
        return "referenced by project files, likely needed"
    if info.get("cache"):
        return "regenerable, review before deleting"
    if info.get("git", {}).get("ignored"):
        return "ignored by git, review before deleting"
    return "no obvious owner, review manually"


def explain(conn, path, snapshot_id=None, include_refs=True):
    target = Path(path).expanduser().absolute()
    if not target.exists():
        raise FileNotFoundError(str(target))

    snapshot = None
    relative = None
    if snapshot_id is not None:
        snapshot = db.get_snapshot(conn, snapshot_id)
        if snapshot is None:
            raise ValueError(f"snapshot not found: {snapshot_id}")
        root = Path(snapshot["root"])
        if not target.is_relative_to(root):
            raise ValueError(f"path is outside snapshot root: {root}")
        relative = os.path.relpath(target, root).replace(os.sep, "/")
    else:
        snapshot, relative = db.find_snapshot_for_path(conn, target)

    stat = target.stat()
    size = _stat_size(stat)
    apparent = max(0, stat.st_size)
    kind = "directory" if target.is_dir() else detect_type(target)
    result = {
        "path": str(target),
        "relative": relative,
        "snapshot_id": snapshot["id"] if snapshot else None,
        "kind": kind,
        "size": size,
        "apparent": apparent,
        "mtime": stat.st_mtime,
        "age": human_age(stat.st_mtime),
        "mode": stat.st_mode,
        "inode": stat.st_ino,
        "links": getattr(stat, "st_nlink", 1),
        "cache": cache_reason(relative or target.name),
        "git": git_info(target),
        "duplicates": [],
        "references": [],
    }

    if target.is_file():
        dimensions = image_dimensions(target, kind)
        if dimensions:
            result["dimensions"] = dimensions
        if snapshot is not None and relative is not None:
            result["duplicates"] = find_duplicates(
                conn, snapshot, relative, size
            )
        if include_refs:
            result["references"] = find_references(target)
    else:
        result["files"] = 0
        result["dirs"] = 0
        result["children"] = []
        if snapshot is not None and relative is not None:
            directories = db.get_dirs(conn, snapshot["id"])
            row = directories.get(relative)
            if row is not None:
                result["size"] = row["size"]
                result["files"] = row["files"]
                result["dirs"] = row["dirs"]
            prefix = "" if relative in (".", "") else relative + "/"
            children = []
            for child_path, child in directories.items():
                if child_path == relative:
                    continue
                if prefix and not child_path.startswith(prefix):
                    continue
                rest = child_path[len(prefix) :]
                if "/" in rest:
                    continue
                children.append((child_path, child["size"]))
            children.sort(key=lambda item: item[1], reverse=True)
            result["children"] = children[:5]

    result["recommendation"] = recommendation(result)
    return result
